import datetime

from django.conf import settings

from apps.operations.services import mask_cpf

NOTICE = (
    "Representação informativa. O Comprovante de Registro de Ponto oficial (PDF com assinatura "
    "eletrônica ICP-Brasil, arts. 80 e 88 da Portaria MTP 671/2021) ainda não está disponível."
)


def _local_iso(moment: datetime.datetime, offset_minutes: int, seconds: bool) -> str:
    local = moment.astimezone(datetime.timezone(datetime.timedelta(minutes=offset_minutes)))
    return local.isoformat(timespec="seconds" if seconds else "minutes")


def build_receipt(record) -> dict:
    """Campos do art. 79 da Portaria 671. CPF mascarado: o terminal é compartilhado.

    Campos que o produto ainda não consegue preencher são listados em `pending_fields`.
    """
    company, unit = record.company, record.unit
    inpi = settings.REP_P_INPI_REGISTRATION
    pending = []
    if not company.tax_id:
        pending.append("empregador.cnpj_cpf")
    if not unit.address:
        pending.append("local_prestacao_servico.endereco")
    if not record.cpf:
        pending.append("trabalhador.cpf")
    if not inpi:
        pending.append("numero_registro_inpi")
    return {
        "title": "Comprovante de Registro de Ponto do Trabalhador",
        "nsr": record.nsr,
        "employer": {
            "name": company.legal_name or company.name,
            "document_type": company.tax_id_type,
            "document": company.tax_id,
            "cei_caepf_cno": company.cei_caepf_cno,
        },
        "service_location": {"unit": unit.name, "address": unit.address},
        "worker": {"name": record.employee_name, "cpf": mask_cpf(record.cpf)},
        "occurred_at": _local_iso(record.occurred_at, record.occurred_offset_minutes, seconds=True),
        "recorded_at": _local_iso(record.recorded_at, record.recorded_offset_minutes, seconds=True),
        "rep_p_inpi_registration": inpi or None,
        "hash_sha256": record.record_hash,
        "hash_version": record.hash_version,
        "signed": False,
        "format": "json-informativo",
        "pending_fields": pending,
        "notice": NOTICE,
    }
