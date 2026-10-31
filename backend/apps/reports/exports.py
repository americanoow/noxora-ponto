"""CSV seguro (sem injeção de fórmula) e PDFs simples do comprovante e do espelho."""

import csv
import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BRAND = colors.HexColor("#1F3A5F")


def safe_cell(value) -> str:
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def csv_bytes(header: list[str], rows) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([safe_cell(v) for v in row])
    return ("﻿" + buffer.getvalue()).encode("utf-8")  # BOM: abre corretamente no Excel


def hm(minutes) -> str:
    minutes = int(minutes or 0)
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def _doc(buffer, title):
    return SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title=title,
        author="Noxora Ponto",
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )


def _table(data, widths=None, header=True):
    table = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C9D3DF")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), BRAND), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
    table.setStyle(TableStyle(style))
    return table


def receipt_pdf(receipt: dict) -> bytes:
    styles = getSampleStyleSheet()
    buffer = io.BytesIO()
    doc = _doc(buffer, receipt["title"])
    employer = receipt["employer"]
    rows = [
        ["NSR", str(receipt["nsr"])],
        ["Empregador", employer.get("name", "")],
        [employer.get("document_type") or "Documento", employer.get("document") or "(pendente)"],
        ["CEI/CAEPF/CNO", employer.get("cei_caepf_cno") or "-"],
        [
            "Local da prestação",
            f"{receipt['service_location'].get('unit', '')} — "
            f"{receipt['service_location'].get('address') or '(endereço pendente)'}",
        ],
        ["Trabalhador", receipt["worker"]["name"]],
        ["CPF", receipt["worker"]["cpf"] or "(pendente)"],
        ["Data e hora da marcação", receipt["occurred_at"]],
        ["Data e hora da gravação", receipt["recorded_at"]],
        ["Registro INPI do REP-P", receipt["rep_p_inpi_registration"] or "(pendente)"],
        ["Hash SHA-256", Paragraph(escape(receipt["hash_sha256"]), styles["Code"])],
    ]
    story = [
        Paragraph(escape(receipt["title"]), styles["Title"]),
        _table(rows, widths=[50 * mm, 125 * mm], header=False),
        Spacer(1, 6 * mm),
        Paragraph(
            escape("Documento SEM assinatura eletrônica. " + receipt.get("notice", "")), styles["Italic"]
        ),
    ]
    if receipt.get("pending_fields"):
        story.append(
            Paragraph(escape("Campos pendentes: " + ", ".join(receipt["pending_fields"])), styles["Normal"])
        )
    doc.build(story)
    return buffer.getvalue()


STATUS = {
    "ok": "OK",
    "inconsistent": "Inconsistente",
    "absent": "Falta",
    "day_off": "Folga",
    "justified": "Abonado",
}


def timesheet_pdf(sheet: dict, *, company_name: str, closing: dict | None = None) -> bytes:
    styles = getSampleStyleSheet()
    buffer = io.BytesIO()
    doc = _doc(buffer, "Espelho de ponto")
    e = sheet["employee"]
    period = sheet["period"]
    story = [
        Paragraph("Espelho de ponto", styles["Title"]),
        # Nomes vêm do cadastro: escapados para que marcação (ex.: <img src=...>) nunca seja interpretada.
        Paragraph(escape(f"{company_name} — {e['name']} (matrícula {e['registration']})"), styles["Normal"]),
        Paragraph(
            escape(f"Período: {period['from']} a {period['to']} · fuso {sheet['timezone']}"), styles["Normal"]
        ),
        Paragraph(
            "Situação: "
            + (
                f"FECHADO em {closing['closed_at']} (hash {closing['snapshot_sha256'][:16]}…)"
                if closing
                else "aberto — valores podem mudar"
            ),
            styles["Normal"],
        ),
        Spacer(1, 4 * mm),
    ]
    rows = [["Data", "Marcações", "Previsto", "Trab.", "Extra", "Débito", "Noturno", "Situação"]]
    for d in sheet["days"]:
        # Transparência do tratamento (Portaria 671): o original desconsiderado continua visível (×).
        marks = " ".join(
            [m["local"][11:16] + ("*" if m["origin"] == "included" else "") for m in d["marks"]]
            + [m["local"][11:16] + "×" for m in d.get("ignored_marks", [])]
        )
        rows.append(
            [
                d["date"][8:10] + "/" + d["date"][5:7],
                Paragraph(escape(marks or "-"), styles["BodyText"]),
                hm(d["expected_minutes"]),
                hm(d["worked_minutes"]),
                hm(d["overtime_minutes"])
                + (f" ({d['overtime_rate_percent']}%)" if d["overtime_minutes"] else ""),
                hm(d["deficit_minutes"]),
                hm(d["night_minutes"]),
                STATUS.get(d["status"], d["status"]) + (" ⚑" if d["issues"] else ""),
            ]
        )
    story.append(
        _table(rows, widths=[14 * mm, 52 * mm, 16 * mm, 16 * mm, 24 * mm, 16 * mm, 16 * mm, 26 * mm])
    )
    story.append(
        Paragraph(
            "* marcação incluída por ajuste aprovado · × marcação original desconsiderada por ajuste "
            "aprovado (o registro original é preservado) · ⚑ dia com ocorrência",
            styles["Italic"],
        )
    )
    t = sheet["totals"]
    story += [
        Spacer(1, 4 * mm),
        _table(
            [
                [
                    "Previsto",
                    "Trabalhado",
                    "Extras",
                    "Débito",
                    "Abonado",
                    "Noturno (reduzido)",
                    "Saldo do período",
                ],
                [
                    hm(t["expected_minutes"]),
                    hm(t["worked_minutes"]),
                    ", ".join(f"{hm(v)} a {k}%" for k, v in t["overtime_by_rate"].items()) or "00:00",
                    hm(t["deficit_minutes"]),
                    hm(t["justified_minutes"]),
                    f"{hm(t['night_minutes'])} ({hm(t['night_reduced_minutes'])})",
                    hm(t["balance_minutes"]),
                ],
            ]
        ),
        Spacer(1, 4 * mm),
        Paragraph(
            "* marcação incluída por ajuste aprovado. ⚑ dia com ocorrência. Horários no fuso da unidade. "
            "Marcações originais permanecem inalteradas no registro de ponto. Cálculo pelas regras "
            f"versionadas {', '.join(str(v['version']) for v in sheet['rule_versions'])} "
            f"({sheet['engine_version']}).",
            styles["Italic"],
        ),
    ]
    doc.build(story)
    return buffer.getvalue()
