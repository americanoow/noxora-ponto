import datetime as dt
from zoneinfo import ZoneInfo

from django.db.models import OuterRef, Subquery
from django.utils import timezone

from apps.operations import services as ops_services
from apps.operations.models import Assignment
from apps.timeclock.models import TimeRecord

from .models import AvailabilitySettings, AvailabilityUpdate, Status


def settings_for(company) -> AvailabilitySettings:
    obj = AvailabilitySettings.objects.filter(company=company).first()
    return obj or AvailabilitySettings(company=company)


def freshness(update, now, stale_after) -> str:
    """confirmed (recente), stale (sem confirmação há muito tempo), expired (venceu) ou unknown."""
    if update is None:
        return "unknown"
    if update.expires_at and update.expires_at <= now:
        return "expired"
    if now - update.set_at > dt.timedelta(minutes=stale_after):
        return "stale"
    return "confirmed"


def board(*, request, company, unit_id=None, sector_id=None):
    """Painel por unidade/setor. Ponto legal só é LIDO como indício de presença (opcional)."""
    now = timezone.now()
    conf = settings_for(company)
    employees = ops_services.visible_employees(request, company).filter(is_active=True)
    current = Assignment.objects.filter(employee=OuterRef("pk")).filter(ops_services.current_q())
    employees = employees.annotate(
        unit_id_now=Subquery(current.values("unit_id")[:1]),
        sector_id_now=Subquery(current.values("sector_id")[:1]),
    ).filter(unit_id_now__isnull=False)
    if unit_id is not None:
        employees = employees.filter(unit_id_now=unit_id)
    if sector_id is not None:
        employees = employees.filter(sector_id_now=sector_id)
    employees = list(employees.order_by("full_name", "id")[:1000])
    ids = [e.pk for e in employees]

    latest = {u.employee_id: u for u in _latest(ids)}

    hints = {}
    if conf.show_punch_hint and ids:
        since = now - dt.timedelta(hours=16)
        rows = TimeRecord.objects.filter(employee_id__in=ids, occurred_at__gte=since).order_by("occurred_at")
        for r in rows.values("employee_id", "occurred_at", "unit__timezone", "unit__name"):
            h = hints.setdefault(r["employee_id"], {"count": 0, "last_at": None, "tz": r["unit__timezone"]})
            h["count"] += 1
            h["last_at"] = r["occurred_at"]
            h["unit_name"] = r["unit__name"]

    from apps.operations.models import Sector, Unit

    units = {u.pk: u for u in Unit.objects.filter(company=company)}
    sectors = {s.pk: s for s in Sector.objects.filter(company=company)}
    groups = {}
    for e in employees:
        key = (e.unit_id_now, e.sector_id_now)
        unit, sector = units.get(e.unit_id_now), sectors.get(e.sector_id_now)
        group = groups.setdefault(
            key,
            {
                "unit": {"id": unit.pk, "name": unit.name} if unit else None,
                "sector": {"id": sector.pk, "name": sector.name} if sector else None,
                "counts": {s: 0 for s in [*Status.values, "unknown"]},
                "stale": 0,
                "employees": [],
            },
        )
        update = latest.get(e.pk)
        fresh = freshness(update, now, conf.stale_after_minutes)
        status = update.status if update and fresh in ("confirmed", "stale") else "unknown"
        group["counts"][status] += 1
        if fresh == "stale":
            group["stale"] += 1
        hint = hints.get(e.pk)
        item = {
            "employee": {"id": e.pk, "name": e.full_name, "registration": e.registration},
            "status": status,
            "status_label": Status(status).label if status != "unknown" else "Sem informação",
            "freshness": fresh,
            "note": update.note if update and status != "unknown" else "",
            "updated_at": update.set_at if update else None,
            "updated_by_source": update.source if update else None,
            "expires_at": update.expires_at if update else None,
            "punch_hint": None,
        }
        if hint:
            local = hint["last_at"].astimezone(ZoneInfo(hint["tz"]))
            item["punch_hint"] = {
                "last_punch_at": hint["last_at"],
                "unit_name": hint["unit_name"],
                "likely_present": hint["count"] % 2 == 1,
                "text": f"Última marcação às {local:%H:%M}" + (f" em {hint['unit_name']}" if hint["unit_name"] else "") + " (indício do ponto, não confirma presença)",
            }
        group["employees"].append(item)
    return {
        "generated_at": now,
        "stale_after_minutes": conf.stale_after_minutes,
        "notice": "Disponibilidade é informação operacional e não altera nem substitui o registro de ponto.",
        "groups": sorted(
            groups.values(),
            key=lambda g: ((g["unit"] or {}).get("name", ""), (g["sector"] or {}).get("name", "")),
        ),
    }


def _latest(ids):
    """Último estado de cada funcionário (DISTINCT ON no PostgreSQL; laço simples nos demais bancos)."""
    from django.db import connection

    rows = AvailabilityUpdate.objects.filter(employee_id__in=ids)
    if connection.vendor == "postgresql":
        return list(rows.order_by("employee_id", "-set_at", "-id").distinct("employee_id"))
    seen, out = set(), []
    for u in rows.order_by("-set_at", "-id"):
        if u.employee_id not in seen:
            seen.add(u.employee_id)
            out.append(u)
    return out


def set_status(*, company, employee, user, status, note="", expires_minutes=None, source):
    expires = timezone.now() + dt.timedelta(minutes=expires_minutes) if expires_minutes else None
    return AvailabilityUpdate.objects.create(
        company=company,
        employee=employee,
        status=status,
        note=note,
        source=source,
        set_by=user,
        expires_at=expires,
    )
