import datetime
from typing import NamedTuple
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, NotFound, PermissionDenied, ValidationError

from apps.devices.models import Device
from apps.operations import services as ops_services

from . import hashing
from .models import NsrCounter, TimeRecord
from .receipt import snapshot_receipt


class IdentificationResult(NamedTuple):
    method: str
    reference: str = ""


class IdentificationRejected(ValidationError):
    pass


class RegistrationOnlyProvider:
    """Identificação apenas pela matrícula. NÃO é identificação forte: só para desenvolvimento.

    Contrato para a etapa 6: um provedor facial implementa `verify(device, employee, payload)` e
    devolve o método e a referência da verificação (nunca o dado biométrico).
    """

    method = "registration"

    def verify(self, *, device, employee, payload) -> IdentificationResult:
        if not settings.TIMECLOCK_ALLOW_REGISTRATION_ONLY:
            raise IdentificationRejected({"identification": "Identificação por matrícula não permitida."})
        return IdentificationResult(self.method)


PROVIDERS = {RegistrationOnlyProvider.method: RegistrationOnlyProvider()}


def _offset_minutes(tz_name: str, moment: datetime.datetime) -> int:
    offset = moment.astimezone(ZoneInfo(tz_name)).utcoffset()
    return int(offset.total_seconds() // 60) if offset is not None else 0


def _existing(device, client_event_id):
    return (
        TimeRecord.objects.select_related("company", "unit", "device")
        .filter(device=device, client_event_id=client_event_id)
        .first()
    )


@transaction.atomic
def record_punch(
    *,
    device,
    registration: str,
    client_event_id,
    declared_kind: str = "",
    device_reported_at: datetime.datetime | None = None,
    identification: dict | None = None,
    credential=None,
):
    """Grava uma marcação. Retorna (registro, criado).

    - Idempotente por (dispositivo, client_event_id): reenvio devolve o registro original.
    - Nunca bloqueia por escala, disponibilidade ou horário (Portaria 671, art. 74).
    - Horário oficial = relógio do servidor; o do aparelho é guardado como informação.
    """
    # Mesmo bloqueio usado por revogação/renovação. A autenticação HTTP pode ter
    # ocorrido antes de uma revogação concorrente.
    device = Device.objects.select_for_update().get(pk=device.pk)
    if credential is not None:
        credential.refresh_from_db()
        if (
            credential.device_id != device.pk
            or credential.revoked_at is not None
            or credential.expires_at <= timezone.now()
        ):
            raise AuthenticationFailed("Credencial sem autorização.")
    if device.status != "active":
        raise AuthenticationFailed("Dispositivo sem autorização.")
    if not device.company.is_active:
        raise PermissionDenied("Empresa inativa.")
    existing = _existing(device, client_event_id)
    if existing is not None:
        return existing, False

    employee = ops_services.employee_for_device(device, registration)
    if employee is None:
        raise NotFound("Matrícula não encontrada nesta unidade.")

    payload = identification or {"method": RegistrationOnlyProvider.method}
    method = payload.get("method")
    provider = PROVIDERS.get(method) if isinstance(method, str) else None
    if provider is None:
        raise ValidationError({"identification": "Método de identificação desconhecido."})
    result = provider.verify(device=device, employee=employee, payload=payload)

    try:
        with transaction.atomic():
            record = _insert(device, employee, client_event_id, declared_kind, device_reported_at, result)
    except IntegrityError:
        # Corrida entre dois envios do mesmo evento: o segundo devolve o primeiro.
        existing = _existing(device, client_event_id)
        if existing is not None:
            return existing, False
        raise
    return record, True


def _insert(device, employee, client_event_id, declared_kind, device_reported_at, identification):
    unit = device.unit
    NsrCounter.objects.get_or_create(unit=unit)
    counter = NsrCounter.objects.select_for_update().get(unit=unit)  # serializa NSR e cadeia por unidade
    nsr = counter.last_nsr + 1

    now = timezone.now()
    offset = _offset_minutes(unit.timezone, now)
    skew = int((device_reported_at - now).total_seconds()) if device_reported_at else None
    prev_hash = counter.last_hash
    record_hash = hashing.compute_hash(
        nsr=nsr,
        occurred_at=now,
        occurred_offset=offset,
        cpf=employee.cpf,
        recorded_at=now,
        recorded_offset=offset,
        collector_code=settings.TIMECLOCK_COLLECTOR_CODE,
        offline=False,
        prev_hash=prev_hash,
    )
    record = TimeRecord.objects.create(
        nsr=nsr,
        unit=unit,
        company_id=device.company_id,
        employee=employee,
        device=device,
        client_event_id=client_event_id,
        occurred_at=now,
        occurred_offset_minutes=offset,
        occurred_local_date=now.astimezone(ZoneInfo(unit.timezone)).date(),
        recorded_at=now,
        recorded_offset_minutes=offset,
        offline=False,
        collector_code=settings.TIMECLOCK_COLLECTOR_CODE,
        device_reported_at=device_reported_at,
        clock_skew_seconds=skew,
        cpf=employee.cpf,
        employee_name=employee.full_name,
        registration=employee.registration,
        receipt_snapshot=snapshot_receipt(device.company, unit),
        declared_kind=declared_kind,
        identification_method=identification.method,
        identification_ref=identification.reference,
        hash_version=hashing.HASH_VERSION,
        prev_hash=prev_hash,
        record_hash=record_hash,
    )
    counter.last_nsr = nsr
    counter.last_hash = record_hash
    counter.save(update_fields=["last_nsr", "last_hash"])
    return record


@transaction.atomic
def verify_unit_chain(unit) -> list[str]:
    """Confere NSR contíguo, encadeamento e hashes de uma unidade. Lista vazia = íntegra."""
    problems = []
    # Leitura consistente com a alocação: uma inserção concorrente não deve
    # produzir um falso alerta entre a leitura dos registros e a do contador.
    counter = NsrCounter.objects.select_for_update().filter(unit=unit).first()
    prev_hash, expected_nsr = "", 1
    last = None
    for r in TimeRecord.objects.filter(unit=unit).order_by("nsr").iterator():
        last = r
        if r.hash_version != hashing.HASH_VERSION:
            problems.append(f"NSR {r.nsr}: versão de hash desconhecida")
        local_date = r.occurred_at.astimezone(
            datetime.timezone(datetime.timedelta(minutes=r.occurred_offset_minutes))
        ).date()
        if r.occurred_local_date != local_date:
            problems.append(f"NSR {r.nsr}: data local inconsistente")
        if r.nsr != expected_nsr:
            problems.append(f"NSR {r.nsr}: esperado {expected_nsr} (lacuna ou duplicidade)")
            expected_nsr = r.nsr
        if r.prev_hash != prev_hash:
            problems.append(f"NSR {r.nsr}: hash anterior não confere com o registro anterior")
        recomputed = hashing.compute_hash(
            nsr=r.nsr,
            occurred_at=r.occurred_at,
            occurred_offset=r.occurred_offset_minutes,
            cpf=r.cpf,
            recorded_at=r.recorded_at,
            recorded_offset=r.recorded_offset_minutes,
            collector_code=r.collector_code,
            offline=r.offline,
            prev_hash=r.prev_hash,
        )
        if recomputed != r.record_hash:
            problems.append(f"NSR {r.nsr}: hash armazenado difere do recalculado")
        prev_hash, expected_nsr = r.record_hash, r.nsr + 1
    if last is None and counter is not None and (counter.last_nsr != 0 or counter.last_hash):
        problems.append("Contador não vazio sem marcações")
    if last is not None and (
        counter is None or counter.last_nsr != last.nsr or counter.last_hash != last.record_hash
    ):
        problems.append("Contador de NSR/último hash não confere com o último registro")
    return problems
