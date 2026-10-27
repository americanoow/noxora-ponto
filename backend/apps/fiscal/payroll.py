"""Exportação dos totais apurados para a folha, por perfil de rubricas da empresa (formato genérico)."""

from apps.reports.exports import csv_bytes

from .models import PAYROLL_EVENTS

PAYROLL_GENERATOR_VERSION = "folha-generica-1"


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
            out.append(f"{registration[:10]:>10}{code[:6]:>6}{start:%Y%m%d}{end:%Y%m%d}{amount}")
        return ("\r\n".join(out) + ("\r\n" if out else "")).encode("ascii", errors="replace")
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
