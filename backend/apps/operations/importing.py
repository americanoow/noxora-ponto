"""Importação de funcionários por CSV: validação completa antes de gravar (tudo ou nada)."""

import csv
import datetime
import io

from django.db import transaction

from . import services
from .models import Employee, Sector, Unit

MAX_ROWS = 2000
MAX_CHARS = 1_000_000
REQUIRED = {"matricula", "nome"}
KNOWN = REQUIRED | {"cpf", "unidade", "setor", "inicio"}


class ImportFileError(Exception):
    pass


def _parse_date(raw):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError("Data inválida. Use AAAA-MM-DD ou DD/MM/AAAA.")


def parse(text):
    if len(text) > MAX_CHARS:
        raise ImportFileError("Arquivo grande demais.")
    text = text.lstrip("﻿")
    first_line = text.splitlines()[0] if text.strip() else ""
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = {(h or "").strip().lower() for h in (reader.fieldnames or [])}
    missing = REQUIRED - headers
    if missing:
        raise ImportFileError(f"Colunas obrigatórias ausentes: {', '.join(sorted(missing))}.")
    unknown = headers - KNOWN
    if unknown:
        raise ImportFileError(f"Colunas não reconhecidas: {', '.join(sorted(unknown))}.")
    rows = []
    for line, raw in enumerate(reader, start=2):
        if len(rows) >= MAX_ROWS:
            raise ImportFileError(f"O arquivo excede {MAX_ROWS} linhas.")
        rows.append((line, {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k}))
    if not rows:
        raise ImportFileError("O arquivo não contém linhas de dados.")
    return rows


def validate(company, rows):
    """Retorna (registros válidos, erros). Erros trazem linha, campo e mensagem legível."""
    errors = []
    units = {u.name.lower(): u for u in Unit.objects.filter(company=company, is_active=True)}
    sectors = {(s.unit_id, s.name.lower()): s for s in Sector.objects.filter(company=company, is_active=True)}
    existing_regs = set(Employee.objects.filter(company=company).values_list("registration", flat=True))
    existing_cpfs = set(
        Employee.objects.filter(company=company).exclude(cpf="").values_list("cpf", flat=True)
    )
    seen_regs, seen_cpfs, records = set(), set(), []

    for line, row in rows:
        before = len(errors)

        def err(field, message, line=line):
            errors.append({"line": line, "field": field, "message": message})

        reg, name = row.get("matricula", ""), row.get("nome", "")
        if not reg:
            err("matricula", "Matrícula obrigatória.")
        elif len(reg) > 30:
            err("matricula", "Matrícula com mais de 30 caracteres.")
        elif reg in existing_regs:
            err("matricula", f"Matrícula {reg} já cadastrada.")
        elif reg in seen_regs:
            err("matricula", f"Matrícula {reg} repetida no arquivo.")
        seen_regs.add(reg)
        if not name:
            err("nome", "Nome obrigatório.")
        elif len(name) > 200:
            err("nome", "Nome com mais de 200 caracteres.")

        cpf = ""
        try:
            cpf = services.validate_cpf(row.get("cpf", ""))
        except ValueError as exc:
            err("cpf", str(exc))
        if cpf and (cpf in existing_cpfs or cpf in seen_cpfs):
            err("cpf", "CPF já cadastrado ou repetido no arquivo.")
        seen_cpfs.add(cpf)

        unit = sector = None
        start = None
        if row.get("unidade"):
            unit = units.get(row["unidade"].lower())
            if unit is None:
                err("unidade", f"Unidade '{row['unidade']}' não encontrada ou inativa.")
            elif row.get("setor"):
                sector = sectors.get((unit.pk, row["setor"].lower()))
                if sector is None:
                    err("setor", f"Setor '{row['setor']}' não encontrado na unidade '{unit.name}'.")
        elif row.get("setor"):
            err("setor", "Informe a unidade para usar um setor.")
        if row.get("inicio"):
            try:
                start = _parse_date(row["inicio"])
            except ValueError as exc:
                err("inicio", str(exc))

        if len(errors) == before:
            records.append(
                {
                    "registration": reg,
                    "full_name": name,
                    "cpf": cpf,
                    "unit": unit,
                    "sector": sector,
                    "start": start,
                }
            )
    return records, errors


def commit(company, records):
    created = []
    with transaction.atomic():
        for r in records:
            employee = Employee.objects.create(
                company=company, registration=r["registration"], full_name=r["full_name"], cpf=r["cpf"]
            )
            if r["unit"] is not None:
                services.assign_unit(
                    employee, company, r["unit"], r["sector"], r["start"] or services.today()
                )
            created.append(employee)
    return created
