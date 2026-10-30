"""Exportação dos totais apurados para a folha, por perfil de rubricas da empresa (formato genérico)."""

from apps.reports.exports import csv_bytes

from .models import PAYROLL_EVENTS

PAYROLL_GENERATOR_VERSION = "folha-generica-2"

# Largura fixa do layout genérico: matrícula em 10 colunas e rubrica em 6, apenas ASCII imprimível.
FIXED_REGISTRATION_WIDTH = 10
FIXED_CODE_WIDTH = 6


class PayrollFormatError(ValueError):
    """Dados que não cabem no layout escolhido: o arquivo NÃO é gerado (nada é truncado ou trocado)."""


def _printable_ascii(text: str) -> bool:
    return text.isascii() and text.isprintable() and text == text.strip()


def check_fixed_layout(rows, codes) -> None:
    """Recusa matrículas e rubricas que não cabem ou não têm representação exata no TXT de largura fixa.

    Truncar `1234567890A` e `1234567890B` para 10 colunas as tornaria a mesma pessoa para o importador, e
    trocar acentos por `?` esconderia o erro: aqui o arquivo é recusado e a lista de problemas é devolvida."""
    problems = []
    for registration, _name, _totals in rows:
        if len(registration) > FIXED_REGISTRATION_WIDTH or not _printable_ascii(registration):
            problems.append(
                f'matrícula "{registration}" '
                f"(máximo de {FIXED_REGISTRATION_WIDTH} caracteres ASCII, sem espaços nas pontas)"
            )
    for event, code in (codes or {}).items():
        if code and (len(code) > FIXED_CODE_WIDTH or not _printable_ascii(code)):
            problems.append(
                f'código de rubrica "{code}" do evento {event} '
                f"(máximo de {FIXED_CODE_WIDTH} caracteres ASCII)"
            )
    if problems:
        raise PayrollFormatError(
            "O layout de largura fixa não comporta: "
            + "; ".join(problems[:10])
            + ("; ..." if len(problems) > 10 else "")
            + ". Use o formato CSV ou ajuste os cadastros."
        )


def event_values(totals: dict) -> dict:
    by_rate = dict(totals["overtime_by_rate"])
    return {
        "worked": totals["worked_minutes"],
        "overtime_50": by_rate.pop("50", 0),
        "overtime_100": by_rate.pop("100", 0),
        "overtime_other": sum(by_rate.values()),
        "night": totals["night_reduced_minutes"],
        "deficit": totals["deficit_minutes"],
        "absences": totals["absences"],
        "justified": totals["justified_minutes"],
        "break_suppressed": totals["break_suppressed_minutes"],
    }


def _hhhmm(minutes: int) -> str:
    return f"{minutes // 60:03d}{minutes % 60:02d}"


def build(profile, rows, *, start, end) -> bytes:
    """`rows`: [(matrícula, nome, totais)]. Só eventos com código no perfil e valor diferente de zero."""
    if profile.file_format == "fixed":
        check_fixed_layout(rows, profile.event_codes)
    lines = []
    for registration, name, totals in rows:
        for event, value in event_values(totals).items():
            code = (profile.event_codes or {}).get(event)
            if not code or not value:
                continue
            lines.append((registration, name, code, event, value))
    if profile.file_format == "fixed":
        out = []
        for registration, _, code, event, value in lines:
            amount = f"{value:05d}" if event == "absences" else _hhhmm(value)
            out.append(f"{registration:>10}{code:>6}{start:%Y%m%d}{end:%Y%m%d}{amount}")
        return ("\r\n".join(out) + ("\r\n" if out else "")).encode("ascii")
    header = [
        "matricula",
        "nome",
        "codigo_rubrica",
        "evento",
        "descricao",
        "quantidade",
        "unidade",
        "inicio",
        "fim",
    ]
    return csv_bytes(
        header,
        [
            [
                registration,
                name,
                code,
                event,
                PAYROLL_EVENTS[event],
                value if event == "absences" else f"{value // 60}:{value % 60:02d}",
                "dias" if event == "absences" else "horas",
                start.isoformat(),
                end.isoformat(),
            ]
            for registration, name, code, event, value in lines
        ],
    )
