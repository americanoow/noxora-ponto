import datetime
from typing import NamedTuple
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, NotFound, PermissionDenied, ValidationError

from apps.devices.models import Device
from apps.operations import services as ops_services
from apps.operations.models import Assignment, Employee

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
    device = Device.objects.select_for_update(no_key=True).get(pk=device.pk)
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

    employee = Employee.objects.select_for_update(no_key=True).get(pk=employee.pk)
    if identification is not None and not isinstance(identification, dict):
        raise IdentificationRejected({"identification": "Identificação inválida."})
    payload = identification or {"method": RegistrationOnlyProvider.method}
    method = payload.get("method")
    provider = PROVIDERS.get(method) if isinstance(method, str) else None
    if provider is None:
        raise ValidationError({"identification": "Método de identificação desconhecido."})
    # Política da empresa: no modo facial só valem verificação facial ou exceção autorizada.
    if device.company.identification_mode == "face" and method not in ("face", "authorized_exception"):
        raise IdentificationRejected({"identification": "Esta empresa exige verificação facial."})
    try:
        result = provider.verify(device=device, employee=employee, payload=payload)
    except IdentificationRejected:
        # Corrida do mesmo evento: o primeiro envio já consumiu o token e gravou a marcação.
        existing = _existing(device, client_event_id)
        if existing is not None:
            return existing, False
        raise

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


def _insert(
    device,
    employee,
    client_event_id,
    declared_kind,
    device_reported_at,
    identification,
    *,
    occurred_at=None,
    offline=False,
    sync_flags=None,
    clock_skew_seconds=None,
):
    """Grava a marcação. Online: ocorrência = gravação = relógio do servidor. Offline: `occurred_at` é o
    horário original já corrigido (ver `resolve_offline_time`) e `recorded_at` é o do recebimento."""
    unit = device.unit
    NsrCounter.objects.get_or_create(unit=unit)
    counter = NsrCounter.objects.select_for_update(no_key=True).get(
        unit=unit
    )  # serializa NSR e cadeia por unidade
    nsr = counter.last_nsr + 1

    recorded_at = timezone.now()
    occurred_at = occurred_at or recorded_at
    recorded_offset = _offset_minutes(unit.timezone, recorded_at)
    occurred_offset = _offset_minutes(unit.timezone, occurred_at)
    if clock_skew_seconds is None and not offline and device_reported_at:
        clock_skew_seconds = int((device_reported_at - recorded_at).total_seconds())
    prev_hash = counter.last_hash
    record_hash = hashing.compute_hash(
        nsr=nsr,
        occurred_at=occurred_at,
        occurred_offset=occurred_offset,
        cpf=employee.cpf,
        recorded_at=recorded_at,
        recorded_offset=recorded_offset,
        collector_code=settings.TIMECLOCK_COLLECTOR_CODE,
        offline=offline,
        prev_hash=prev_hash,
    )
    record = TimeRecord.objects.create(
        nsr=nsr,
        unit=unit,
        company_id=device.company_id,
        employee=employee,
        device=device,
        client_event_id=client_event_id,
        occurred_at=occurred_at,
        occurred_offset_minutes=occurred_offset,
        occurred_local_date=occurred_at.astimezone(ZoneInfo(unit.timezone)).date(),
        recorded_at=recorded_at,
        recorded_offset_minutes=recorded_offset,
        offline=offline,
        collector_code=settings.TIMECLOCK_COLLECTOR_CODE,
        device_reported_at=device_reported_at,
        clock_skew_seconds=clock_skew_seconds,
        cpf=employee.cpf,
        employee_name=employee.full_name,
        registration=employee.registration,
        receipt_snapshot=snapshot_receipt(device.company, unit),
        sync_flags=list(sync_flags or []),
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


# ---------- Sincronização de marcações feitas offline (etapa 7) ----------

OFFLINE_METHOD = "registration_offline"

# Sinalizações gravadas em `sync_flags` (informativas; a revisão/ajuste é da etapa 9).
OFFLINE_FLAGS = {
    "clock_unverified": "Tablet sem medição do desvio de relógio",
    "clock_skew_large": "Relógio do tablet com desvio acima do tolerado",
    "clock_offset_stale": "Desvio de relógio medido há muito tempo",
    "time_in_future": "Horário corrigido no futuro; limitado ao recebimento",
    "before_device_activation": "Horário anterior à ativação do tablet",
    "employee_inactive": "Funcionário inativo na sincronização",
    "not_assigned_to_unit": "Funcionário sem lotação nesta unidade na data",
}

REJECT_REASONS = {
    "invalid": "Dados do evento inválidos",
    "offline_not_allowed": "A empresa não permite marcação offline",
    "unsupported_identification": "Identificação offline só por matrícula",
    "unknown_registration": "Matrícula não encontrada na empresa",
    "too_old": "Evento mais antigo que o limite de sincronização",
}


def resolve_offline_time(*, now, device, reported_at, offset_seconds, offset_measured_at):
    """Horário de ocorrência corrigido e flags. Retorna (occurred_at|None, flags, skew_segundos|None).

    `offset_seconds` = servidor − aparelho na última medição. None em `occurred_at` = evento antigo demais.
    Nunca descarta por relógio errado, exceto o que ultrapassa o limite de idade.
    """
    flags: list[str] = []
    if offset_seconds is None:
        corrected = reported_at
        flags.append("clock_unverified")
        skew = None
    else:
        corrected = reported_at + datetime.timedelta(seconds=offset_seconds)
        skew = -offset_seconds
        if abs(offset_seconds) > settings.OFFLINE_CLOCK_SKEW_FLAG_SECONDS:
            flags.append("clock_skew_large")
        stale = datetime.timedelta(hours=settings.OFFLINE_OFFSET_STALE_HOURS)
        if offset_measured_at is None or abs(corrected - offset_measured_at) > stale:
            flags.append("clock_offset_stale")
    if corrected < now - datetime.timedelta(days=settings.OFFLINE_MAX_AGE_DAYS):
        return None, flags, skew
    occurred = corrected
    if corrected > now:
        occurred = now
        if corrected > now + datetime.timedelta(seconds=settings.OFFLINE_FUTURE_TOLERANCE_SECONDS):
            flags.append("time_in_future")
    tolerance = datetime.timedelta(seconds=settings.OFFLINE_FUTURE_TOLERANCE_SECONDS)
    if device.activated_at and corrected < device.activated_at - tolerance:
        flags.append("before_device_activation")
    return occurred, flags, skew


def _assignment_covers(employee, unit_id, local_date) -> bool:
    return (
        Assignment.objects.filter(employee=employee, unit_id=unit_id, valid_from__lte=local_date)
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=local_date))
        .exists()
    )


def _rejected(event_id, reason, flags=None):
    return {"client_event_id": event_id, "status": "rejected", "reason": reason, "flags": flags or []}


def process_offline_event(*, device, credential, event_id, data):
    """Processa UM evento de fila offline em sua própria transação. Retorna um dicionário de resultado.

    - Idempotente por (dispositivo, client_event_id): evento já gravado vira `duplicate`.
    - Falha de autenticação/autorização levanta exceção (interrompe o lote; o reenvio é seguro).
    - Recusas (`rejected`) não gravam nada e permanecem visíveis para tratamento humano.
    """
    with transaction.atomic():
        locked = Device.objects.select_for_update(no_key=True).get(pk=device.pk)
        if credential is not None:
            credential.refresh_from_db()
            if (
                credential.device_id != locked.pk
                or credential.revoked_at is not None
                or credential.expires_at <= timezone.now()
            ):
                raise AuthenticationFailed("Credencial sem autorização.")
        if locked.status != "active":
            raise AuthenticationFailed("Dispositivo sem autorização.")
        company = locked.company
        if not company.is_active:
            raise PermissionDenied("Empresa inativa.")

        existing = _existing(locked, event_id)
        if existing is not None:
            return {
                "client_event_id": event_id,
                "status": "duplicate",
                "record": existing,
                "flags": existing.sync_flags,
            }
        if company.offline_policy != "registration_only":
            return _rejected(event_id, "offline_not_allowed")
        identification = data.get("identification")
        if identification is not None and (
            not isinstance(identification, dict) or identification.get("method") not in (None, "registration")
        ):
            return _rejected(event_id, "unsupported_identification")

        employee = Employee.objects.filter(
            company_id=locked.company_id, registration=data["registration"]
        ).first()
        if employee is None:
            return _rejected(event_id, "unknown_registration")

        now = timezone.now()
        occurred, flags, skew = resolve_offline_time(
            now=now,
            device=locked,
            reported_at=data["device_reported_at"],
            offset_seconds=data.get("clock_offset_seconds"),
            offset_measured_at=data.get("offset_measured_at"),
        )
        if occurred is None:
            return _rejected(event_id, "too_old", flags)

        employee = Employee.objects.select_for_update(no_key=True).get(pk=employee.pk)
        local_date = occurred.astimezone(ZoneInfo(locked.unit.timezone)).date()
        if not employee.is_active:
            flags.append("employee_inactive")
        if not _assignment_covers(employee, locked.unit_id, local_date):
            flags.append("not_assigned_to_unit")
        try:
            with transaction.atomic():
                record = _insert(
                    locked,
                    employee,
                    event_id,
                    data.get("declared_kind", ""),
                    data["device_reported_at"],
                    IdentificationResult(OFFLINE_METHOD),
                    occurred_at=occurred,
                    offline=True,
                    sync_flags=flags,
                    clock_skew_seconds=skew,
                )
        except IntegrityError:
            existing = _existing(locked, event_id)  # corrida entre dois envios do mesmo evento
            if existing is not None:
                return {
                    "client_event_id": event_id,
                    "status": "duplicate",
                    "record": existing,
                    "flags": existing.sync_flags,
                }
            raise
        return {"client_event_id": event_id, "status": "confirmed", "record": record, "flags": flags}


@transaction.atomic
def verify_unit_chain(unit) -> list[str]:
    """Confere NSR contíguo, encadeamento e hashes de uma unidade. Lista vazia = íntegra."""
    problems = []
    # Leitura consistente com a alocação: uma inserção concorrente não deve
    # produzir um falso alerta entre a leitura dos registros e a do contador.
    counter = NsrCounter.objects.select_for_update(no_key=True).filter(unit=unit).first()
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
