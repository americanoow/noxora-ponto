from django.db import IntegrityError, transaction
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.services import get_or_invite_user, send_password_reset
from apps.audit import services as audit
from apps.audit.models import AuditLog

from .models import Company, Membership, Role
from .permissions import require_role, resolve_company
from .serializers import (
    CompanyCreateSerializer,
    CompanySerializer,
    CompanyUpdateSerializer,
    MembershipCreateSerializer,
    MembershipSerializer,
    MembershipUpdateSerializer,
)


def _require_platform_admin(request):
    if not request.user.is_platform_admin:
        raise PermissionDenied("Operação restrita à equipe da plataforma.")


class CompanyListView(APIView):
    def get(self, request):
        if request.user.is_platform_admin:
            companies = Company.objects.all()
        else:
            companies = Company.objects.filter(
                is_active=True, memberships__user=request.user, memberships__is_active=True
            ).distinct()
        return Response(CompanySerializer(companies, many=True).data)

    def post(self, request):
        _require_platform_admin(request)
        data = CompanyCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        with transaction.atomic():
            company = Company.objects.create(name=v["name"])
            admin, created = get_or_invite_user(v["admin_email"], v["admin_name"])
            Membership.objects.create(user=admin, company=company, role=Role.COMPANY_ADMIN)
            audit.record(request, "company.created", company=company, target=company, admin_email=admin.email)
        if created:
            send_password_reset(admin, invite=True)
        return Response(CompanySerializer(company).data, status=status.HTTP_201_CREATED)


class CompanyDetailView(APIView):
    def get(self, request, company_id):
        return Response(CompanySerializer(resolve_company(request, company_id)).data)

    def patch(self, request, company_id):
        _require_platform_admin(request)
        company = Company.objects.filter(pk=company_id).first()
        if company is None:
            raise Http404
        data = CompanyUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        changes = data.validated_data
        for field, value in changes.items():
            setattr(company, field, value)
        company.save(update_fields=list(changes) or None)
        audit.record(request, "company.updated", company=company, target=company, changes=sorted(changes))
        return Response(CompanySerializer(company).data)


class MemberListView(APIView):
    def get(self, request, company_id):
        company = resolve_company(request, company_id)
        require_role(request, Role.COMPANY_ADMIN)
        members = Membership.objects.filter(company=company).select_related("user")
        return Response(MembershipSerializer(members, many=True).data)

    def post(self, request, company_id):
        company = resolve_company(request, company_id)
        require_role(request, Role.COMPANY_ADMIN)
        data = MembershipCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        try:
            with transaction.atomic():
                user, created = get_or_invite_user(v["email"], v["name"])
                membership = Membership.objects.create(user=user, company=company, role=v["role"])
                audit.record(request, "member.created", company=company, target=membership, role=v["role"])
        except IntegrityError:
            return Response({"detail": "Este usuário já possui vínculo com a empresa."}, status=409)
        if created:
            send_password_reset(user, invite=True)
        return Response(MembershipSerializer(membership).data, status=status.HTTP_201_CREATED)


class MemberDetailView(APIView):
    def patch(self, request, company_id, member_id):
        company = resolve_company(request, company_id)
        actor = require_role(request, Role.COMPANY_ADMIN)
        # O filtro por empresa impede alcançar vínculo de outra empresa por id.
        membership = Membership.objects.filter(company=company, pk=member_id).select_related("user").first()
        if membership is None:
            raise Http404
        if membership.pk == actor.pk:
            raise PermissionDenied("Você não pode alterar o próprio vínculo.")
        data = MembershipUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        changes = data.validated_data
        for field, value in changes.items():
            setattr(membership, field, value)
        membership.save(update_fields=list(changes) or None)
        audit.record(
            request,
            "member.updated",
            company=company,
            target=membership,
            **{k: v for k, v in changes.items()},
        )
        return Response(MembershipSerializer(membership).data)


class AuditListView(APIView):
    def get(self, request, company_id):
        company = resolve_company(request, company_id)
        if request.membership is not None:
            require_role(request, Role.COMPANY_ADMIN)
        # Administrador da plataforma chega aqui sem papel; o acesso já foi auditado.
        logs = AuditLog.objects.filter(company=company)[:100]
        return Response(
            [
                {
                    "id": log.pk,
                    "created_at": log.created_at,
                    "actor_email": log.actor_email,
                    "action": log.action,
                    "target_type": log.target_type,
                    "target_id": log.target_id,
                }
                for log in logs
            ]
        )
