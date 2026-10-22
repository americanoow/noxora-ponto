"""Hash encadeado da marcação (Portaria 671/2021, Anexo IX itens 6.5 e 10; Anexo V histórico, tipo 7).

IMPORTANTE: a especificação vigente do AFD está no portal gov.br (a Portaria MTP 1.486/2022 revogou
os anexos com os layouts). Esta versão implementa o layout histórico lido no texto consolidado e
precisa ser conferida com a especificação vigente (ver docs/requisitos-rep-p.md, pendência 1).
Por isso cada registro guarda `hash_version`: uma nova versão pode ser adotada sem reescrever o passado.
"""

import datetime
import hashlib

HASH_VERSION = "v1-anexo-v-historico"
RECORD_TYPE = "7"


def format_dh(moment: datetime.datetime, offset_minutes: int) -> str:
    """`AAAA-MM-ddThh:mm:00±ZZZZ`: minutos, segundos fixos em 00, fuso do momento (24 caracteres)."""
    local = moment.astimezone(datetime.timezone(datetime.timedelta(minutes=offset_minutes)))
    sign = "+" if offset_minutes >= 0 else "-"
    hours, minutes = divmod(abs(offset_minutes), 60)
    return f"{local:%Y-%m-%dT%H:%M}:00{sign}{hours:02d}{minutes:02d}"


def compute_hash(
    *,
    nsr: int,
    occurred_at: datetime.datetime,
    occurred_offset: int,
    cpf: str,
    recorded_at: datetime.datetime,
    recorded_offset: int,
    collector_code: str,
    offline: bool,
    prev_hash: str,
) -> str:
    """SHA-256 sobre: NSR(9) tipo DH-marcação CPF(12) DH-gravação coletor(2) on/off(1) hash-anterior."""
    payload = (
        f"{nsr:09d}"
        + RECORD_TYPE
        + format_dh(occurred_at, occurred_offset)
        + (cpf or "").rjust(12, "0")
        + format_dh(recorded_at, recorded_offset)
        + collector_code
        + ("1" if offline else "0")
        + prev_hash
    )
    return hashlib.sha256(payload.encode("ascii")).hexdigest()
