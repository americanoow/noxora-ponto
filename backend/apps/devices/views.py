from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.operations import services as ops_services
from apps.operations.views import _visible_units, admin_company, is_admin, reader_company

from . import services
from .auth import ActivationRateThrottle, DeviceAuthentication, DeviceRateThrottle, IsDevice
from .models import Device
from .serializers import (
    ActivateSerializer,
    DeviceCreateSerializer,
    DeviceSerializer,
    DeviceUpdateSerializer,
    HeartbeatSerializer,
    LocationEvidenceSerializer,
    LocationSerializer,
)


def _devices_for(request, company):
    devices = Device.objects.filter(company=company).select_related("unit")
    if is_admin(request):
        return devices
    return devices.filter(unit__in=_visible_units(request, company))


def _device_or_404(request, company, device_id):
    query = _devices_for(request, company)
    if request.method in ("POST", "PATCH"):
        query = query.select_for_update(of=("self",), no_key=True)
    device = query.filter(pk=device_id).first()
    if device is None:
        raise Http404
    return device


def _actor(device):
    return f"dispositivo:{device.pk}"


# ---------- Painel administrativo ----------


class DeviceListView(APIView):
    def get(self, request, company_id):
        company = reader_company(request, company_id)
        return Response(DeviceSerializer(_devices_for(request, company), many=True).data)

    def post(self, request, company_id):
        company = admin_company(request, company_id)
        data = DeviceCreateSerializer(data=request.data, context={"company": company})
        data.is_valid(raise_exception=True)
        with transaction.atomic():
            device = Device.objects.create(company=company, **data.validated_data)
            code, record = services.new_activation_code(device)
            audit.record(request, "device.created", company=company, target=device)
        return Response(
            {
                **DeviceSerializer(device).data,
                "activation_code": code,
                "activation_expires_at": record.expires_at,
            },
            status=201,
            headers={"Cache-Control": "no-store"},
        )


class DeviceDetailView(APIView):
    def get(self, request, company_id, device_id):
        company = reader_company(request, company_id)
        return Response(DeviceSerializer(_device_or_404(request, company, device_id)).data)

    @transaction.atomic
    def patch(self, request, company_id, device_id):
        company = admin_company(request, company_id)
        device = _device_or_404(request, company, device_id)
        data = DeviceUpdateSerializer(data=request.data, context={"company": company})
        data.is_valid(raise_exception=True)
        v = data.validated_data
        collect = v.get("collect_location", device.collect_location)
        justification = v.get("location_justification", device.location_justification).strip()
        if collect and not justification:
            raise ValidationError(
                {"location_justification": "Informe a justificativa para coletar localização."}
            )
        if not collect:
            justification = ""
        for field in ("name", "unit"):
            if field in v:
                setattr(device, field, v[field])
        device.collect_location, device.location_justification = collect, justification
        with transaction.atomic():
            device.save()
            audit.record(request, "device.updated", company=company, target=device, changes=sorted(v))
        return Response(DeviceSerializer(device).data)


class DeviceRevokeView(APIView):
    @transaction.atomic
    def post(self, request, company_id, device_id):
        company = admin_company(request, company_id)
        device = _device_or_404(request, company, device_id)
        with transaction.atomic():
            services.revoke(device)
            audit.record(request, "device.revoked", company=company, target=device)
        return Response(DeviceSerializer(device).data)


class DeviceReissueView(APIView):
    """Renovação: o tablet atual perde o acesso e o novo código reativa o mesmo cadastro."""

    @transaction.atomic
    def post(self, request, company_id, device_id):
        company = admin_company(request, company_id)
        device = _device_or_404(request, company, device_id)
        if not device.unit.is_active:
            raise ValidationError({"unit": "A unidade do dispositivo está inativa."})
        with transaction.atomic():
            code = services.reissue(device)
            record = device.activation_codes.filter(used_at__isnull=True).latest("id")
            audit.record(request, "device.reissued", company=company, target=device)
        return Response(
            {
                **DeviceSerializer(device).data,
                "activation_code": code,
                "activation_expires_at": record.expires_at,
            },
            headers={"Cache-Control": "no-store"},
        )


class DeviceLocationsView(APIView):
    def get(self, request, company_id, device_id):
        company = admin_company(request, company_id)
        device = _device_or_404(request, company, device_id)
        return Response(LocationEvidenceSerializer(device.locations.all()[:50], many=True).data)


# ---------- API do tablet ----------


class DeviceView(APIView):
    authentication_classes = [DeviceAuthentication]
    permission_classes = [IsDevice]
    throttle_classes = [DeviceRateThrottle]


def _scope_payload(device):
    return {
        "device_id": device.pk,
        "name": device.name,
        "company": {"id": device.company_id, "name": device.company.name},
        "unit": {"id": device.unit_id, "name": device.unit.name, "timezone": device.unit.timezone},
        "collect_location": device.collect_location,
        "identification_mode": device.company.identification_mode,
        "offline_policy": device.company.offline_policy,
        "server_time": timezone.now(),
    }


class ActivateView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ActivationRateThrottle]
    throttle_scope = "device_activation"

    @transaction.atomic
    def post(self, request):
        data = ActivateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        device, token = services.activate(
            v["code"], app_version=v["app_version"], hardware_hint=v["hardware_hint"]
        )
        audit.record(
            request, "device.activated", company=device.company, target=device, actor_email=_actor(device)
        )
        device = Device.objects.select_related("company", "unit").get(pk=device.pk)
        return Response(
            {"token": token, **_scope_payload(device)}, status=201, headers={"Cache-Control": "no-store"}
        )


class DeviceMeView(DeviceView):
    def get(self, request):
        return Response(_scope_payload(request.device))


class HeartbeatView(DeviceView):
    def post(self, request):
        data = HeartbeatSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        device = request.device
        device.last_seen_at = timezone.now()
        fields = ["last_seen_at"]
        if data.validated_data["app_version"]:
            device.app_version = data.validated_data["app_version"]
            fields.append("app_version")
        device.save(update_fields=fields)
        return Response(_scope_payload(device))


class RotateCredentialView(DeviceView):
    @transaction.atomic
    def post(self, request):
        token = services.rotate(request.auth)
        audit.record(
            request,
            "device.credential_rotated",
            company=request.device.company,
            target=request.device,
            actor_email=_actor(request.device),
        )
        return Response({"token": token}, headers={"Cache-Control": "no-store"})


class LocationView(DeviceView):
    @transaction.atomic
    def post(self, request):
        device = Device.objects.select_for_update(no_key=True).get(pk=request.device.pk)
        request.auth.refresh_from_db()
        if (
            device.status != "active"
            or request.auth.revoked_at is not None
            or request.auth.expires_at <= timezone.now()
        ):
            raise ValidationError({"detail": "Dispositivo sem autorização."})
        if not device.collect_location:
            # Nada é gravado: a coleta precisa estar ligada e justificada pelo administrador.
            return Response(
                {"detail": "A coleta de localização não está habilitada para este dispositivo."}, status=409
            )
        data = LocationSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        device.locations.create(**data.validated_data)
        return Response(status=201)


class RosterLookupView(DeviceView):
    """Busca por matrícula exata, limitada aos funcionários ativos lotados na unidade do aparelho."""

    def get(self, request):
        registration = request.query_params.get("registration", "").strip()
        if not registration:
            raise ValidationError({"registration": "Informe a matrícula."})
        employee = ops_services.employee_for_device(request.device, registration)
        if employee is None:
            raise Http404
        return Response(
            {"id": employee.pk, "registration": employee.registration, "full_name": employee.full_name}
        )
