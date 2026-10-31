"""Dados pessoais do próprio funcionário (LGPD, art. 18, I, II e V): confirmação, acesso e portabilidade.

Reúne o que a empresa guarda sobre o titular neste sistema, em formato aberto (JSON). Nunca inclui o
modelo biométrico, chaves, tokens ou dados de outras pessoas (só o e-mail de quem decidiu um pedido ou
lançou algo, porque isso faz parte do histórico do próprio titular).
"""

import datetime as dt

from django.db.models import Q
from django.utils import timezone

from apps.attendance.models import DayJustification, HourBankEntry, PunchAdjustment
from apps.audit.models import AuditLog
from apps.availability.models import AvailabilityUpdate
from apps.biometrics.models import BiometricConsent, BiometricTemplate
from apps.operations.models import Assignment, EmployeeSchedule
from apps.timeclock.models import TimeRecord

from .models import TimesheetAcknowledgement

FORMAT_VERSION = "dados-pessoais-1"
ACCESS_LOG_DAYS = 180  # histórico de acessos da própria conta incluído no arquivo


def _email(user):
    return user.email if user else None


def collect(employee, user) -> dict:
    company = employee.company
    since = timezone.now() - dt.timedelta(days=ACCESS_LOG_DAYS)
    return {
        "formato": FORMAT_VERSION,
        "gerado_em": timezone.now(),
        "aviso": (
            "Estes são os dados que a empresa guarda sobre você neste sistema. Registros de ponto não podem "
            "ser apagados enquanto a lei exigir que sejam guardados; correções são feitas por pedido de "
            "ajuste. Para corrigir dados cadastrais, fale com o RH da empresa."
        ),
        "empresa": {"nome": company.name, "razao_social": company.legal_name, "documento": company.tax_id},
        "titular": {
            "nome": employee.full_name,
            "matricula": employee.registration,
            "cpf": employee.cpf,
            "admissao": employee.admission_date,
            "ativo": employee.is_active,
            "e_mail_de_acesso": _email(employee.access_user),
            "cadastrado_em": employee.created_at,
        },
        "lotacoes": [
            {
                "unidade": a.unit.name,
                "setor": a.sector.name if a.sector else None,
                "desde": a.valid_from,
                "ate": a.valid_to,
            }
            for a in Assignment.objects.filter(employee=employee).select_related("unit", "sector")
        ],
        "jornadas": [
            {"jornada": s.schedule.name, "desde": s.valid_from, "ate": s.valid_to}
            for s in EmployeeSchedule.objects.filter(employee=employee).select_related("schedule")
        ],
        "biometria": {
            "observacao": "O modelo do rosto é criptografado e nunca é exportado; a foto não é guardada.",
            "consentimentos": [
                {
                    "versao_do_termo": c.policy_version,
                    "referencia_do_termo": c.evidence_ref,
                    "registrado_em": c.granted_at,
                    "retirado_em": c.revoked_at,
                }
                for c in BiometricConsent.objects.filter(employee=employee).order_by("granted_at")
            ],
            "cadastros_do_rosto": [
                {"situacao": t.status, "criado_em": t.created_at, "apagado_em": t.deleted_at}
                for t in BiometricTemplate.objects.filter(employee=employee).order_by("created_at")
            ],
        },
        "marcacoes": [
            {
                "nsr": r.nsr,
                "unidade": r.unit.name,
                "data_hora": r.occurred_at,
                "fuso_minutos": r.occurred_offset_minutes,
                "gravada_em": r.recorded_at,
                "sem_internet": r.offline,
                "identificacao": r.identification_method,
                "tipo_informado": r.declared_kind,
                "sinalizacoes": r.sync_flags or [],
                "hash_sha256": r.record_hash,
            }
            for r in TimeRecord.objects.filter(employee=employee)
            .select_related("unit")
            .order_by("occurred_at")
        ],
        "ajustes": [
            {
                "tipo": a.kind,
                "data_de_referencia": a.reference_date,
                "horario": a.occurred_at,
                "motivo": a.reason,
                "situacao": a.status,
                "pedido_em": a.requested_at,
                "decidido_por": _email(a.decided_by),
                "decidido_em": a.decided_at,
                "observacao": a.decision_note,
            }
            for a in PunchAdjustment.objects.filter(employee=employee).select_related("decided_by")
        ],
        "justificativas": [
            {
                "data": j.date,
                "tipo": j.kind,
                "minutos": j.minutes,
                "motivo": j.reason,
                "documento": j.document_ref,
                "situacao": j.status,
                "pedido_em": j.requested_at,
                "decidido_por": _email(j.decided_by),
                "decidido_em": j.decided_at,
                "observacao": j.decision_note,
            }
            for j in DayJustification.objects.filter(employee=employee).select_related("decided_by")
        ],
        "banco_de_horas": [
            {
                "tipo": h.kind,
                "data": h.date,
                "minutos": h.minutes,
                "motivo": h.reason,
                "estorno_de": h.reverses_id,
                "lancado_por": _email(h.created_by),
                "lancado_em": h.created_at,
            }
            for h in HourBankEntry.objects.filter(employee=employee).select_related("created_by")
        ],
        "ciencias_de_fechamento": [
            {
                "periodo": f"{a.closing.start} a {a.closing.end}",
                "registrada_em": a.acknowledged_at,
                "comentario": a.comment,
            }
            for a in TimesheetAcknowledgement.objects.filter(employee=employee).select_related("closing")
        ],
        "situacao_informada": [
            {"situacao": u.status, "observacao": u.note, "origem": u.source, "em": u.set_at}
            for u in AvailabilityUpdate.objects.filter(employee=employee).order_by("set_at")
        ],
        "acessos_da_conta": [
            {"acao": log.action, "em": log.created_at, "ip": log.ip_address}
            for log in AuditLog.objects.filter(actor=user, created_at__gte=since)
            .filter(Q(company=company) | Q(company__isnull=True))
            .only("action", "created_at", "ip_address")
            .order_by("created_at")
        ],
    }
