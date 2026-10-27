"""Arquivo Fonte de Dados (AFD) do REP-P — geração a partir da ARP (marcações), por estabelecimento.

ESTADO DA CONFERÊNCIA (ver docs/requisitos-rep-p.md):
- Registro tipo 7: campos e tamanhos conferidos com o leiaute AFD do portal gov.br na etapa 5
  (NSR 9, tipo 1, DH marcação 24, CPF 12, DH gravação 24, coletor 2, on/off 1, hash 64 = 137).
- Registros tipo 1 (cabeçalho, 302) e tipo 9 (trailer, 64): reconstruídos do Anexo V; coerentes com
  indícios independentes (INPI em 190–206; quantidade de tipo 7 em 055–063), mas **não conferidos**
  com o PDF oficial nesta sessão (portal inacessível na rede da nuvem). Versão do leiaute, variante do
  CRC-16, preenchimento (zeros × espaços) e codificação de caracteres exigem **validação especializada**.
- A assinatura CAdES (.p7s, ICP-Brasil; art. 88) é **externa** e não é gerada aqui.
Por isso cada arquivo informa `AFD_GENERATOR_VERSION`; mudanças futuras criam nova versão.
"""

import datetime as dt

from django.conf import settings

from apps.timeclock.hashing import format_dh

AFD_GENERATOR_VERSION = "afd-noxora-1"
LINE_END = "\r\n"


def crc16(data: bytes) -> str:
    """CRC-16 (polinômio 0x8005 refletido, valor inicial 0 — CRC-16/ARC), 4 dígitos hexadecimais.

    HIPÓTESE: a variante exigida pelo leiaute precisa ser confirmada com um vetor oficial.
    """
    crc = 0x0000
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return f"{crc:04X}"


def _alpha(value: str, size: int) -> str:
    value = (value or "")[:size]
    return value.ljust(size)


def _num(value, size: int) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())[:size]
    return digits.rjust(size, "0")


def header(*, company, start: dt.date, end: dt.date, generated_at: dt.datetime, offset_minutes: int) -> str:
    kind = {"CNPJ": "1", "CPF": "2"}.get(company.tax_id_type, "1")
    developer_kind = {"CNPJ": "1", "CPF": "2"}.get(settings.REP_P_DEVELOPER_TAX_ID_TYPE, "1")
    body = (
        "000000000"
        + "1"
        + kind
        + _num(company.tax_id, 14)
        + _num(company.cei_caepf_cno, 14)
        + _alpha(company.legal_name or company.name, 150)
        + _alpha(settings.REP_P_INPI_REGISTRATION, 17)
        + start.isoformat()
        + end.isoformat()
        + format_dh(generated_at, offset_minutes)
        + _num(settings.AFD_LAYOUT_VERSION, 3)
        + developer_kind
        + _num(settings.REP_P_DEVELOPER_TAX_ID, 14)
        + _alpha("", 30)  # modelo do REP-C: não se aplica ao REP-P
    )
    assert len(body) == 298, len(body)
    return body + crc16(body.encode("latin-1", errors="replace"))


def record_7(r) -> str:
    line = (
        f"{r.nsr:09d}"
        + "7"
        + format_dh(r.occurred_at, r.occurred_offset_minutes)
        + (r.cpf or "").rjust(12, "0")
        + format_dh(r.recorded_at, r.recorded_offset_minutes)
        + (r.collector_code or "01")[:2].rjust(2, "0")
        + ("1" if r.offline else "0")
        + r.record_hash
    )
    assert len(line) == 137, len(line)
    return line


def trailer(count_7: int) -> str:
    line = "999999999" + "0" * 9 * 5 + f"{count_7:09d}" + "9"
    assert len(line) == 64
    return line


def build_afd(*, company, unit, records, start, end, generated_at=None) -> tuple[bytes, dict]:
    """Gera o AFD de UMA unidade (estabelecimento). `records` em ordem de NSR. Retorna (bytes, metadados)."""
    from zoneinfo import ZoneInfo

    generated_at = generated_at or dt.datetime.now(dt.UTC)
    offset = generated_at.astimezone(ZoneInfo(unit.timezone)).utcoffset()
    offset_minutes = int(offset.total_seconds() // 60) if offset else 0
    lines = [
        header(
            company=company, start=start, end=end, generated_at=generated_at, offset_minutes=offset_minutes
        )
    ]
    pending = []
    count = 0
    for r in records:
        lines.append(record_7(r))
        count += 1
        if not r.cpf:
            pending.append(f"NSR {r.nsr}: CPF do trabalhador ausente")
    lines.append(trailer(count))
    if not company.tax_id:
        pending.append("Empregador sem CNPJ/CPF")
    if not settings.REP_P_INPI_REGISTRATION:
        pending.append("Registro do REP-P no INPI não configurado")
    if not settings.REP_P_DEVELOPER_TAX_ID:
        pending.append("CNPJ do desenvolvedor do REP-P não configurado")
    content = (LINE_END.join(lines) + LINE_END).encode("latin-1", errors="replace")
    return content, {
        "generator_version": AFD_GENERATOR_VERSION,
        "layout_version": settings.AFD_LAYOUT_VERSION,
        "records": count,
        "signed": False,
        "pending": pending,
        "notice": (
            "AFD sem assinatura CAdES (ICP-Brasil); cabeçalho, trailer e CRC a conferir no leiaute oficial."
        ),
    }
