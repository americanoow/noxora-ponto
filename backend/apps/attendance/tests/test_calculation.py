"""Cenários de referência da apuração (funções puras). Os valores esperados seguem os parâmetros padrão,
que são hipóteses a validar com especialista (ver calculation.DEFAULT_PARAMS_REFS)."""

import datetime as dt
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from apps.attendance.calculation import (
    DEFAULT_PARAMS,
    EmployeeContext,
    Mark,
    compute_period,
    totals,
    validate_params,
)

TZ = ZoneInfo("America/Sao_Paulo")
P = validate_params({})
MON = dt.date(2026, 10, 19)  # segunda-feira


def at(day, hhmm, plus_days=0):
    h, m = map(int, hhmm.split(":"))
    return dt.datetime.combine(day + dt.timedelta(days=plus_days), dt.time(h, m), tzinfo=TZ)


def marks(day, *times):
    out = []
    for t in times:
        plus = 1 if t.startswith("+") else 0
        out.append(Mark(at(day, t.lstrip("+"), plus)))
    return out


def ctx(start="08:00", end="17:00", brk=60, weekdays=range(5), holidays=None):
    day = SimpleNamespace(
        start_time=dt.time.fromisoformat(start), end_time=dt.time.fromisoformat(end), break_minutes=brk
    )
    return EmployeeContext(
        tz=TZ,
        schedule_for=lambda d: day if d.weekday() in weekdays else None,
        holiday_for=lambda d: (holidays or {}).get(d, ""),
    )


def one(m, c=None, day=MON, params=P):
    return compute_period(start=day, end=day, marks=m, ctx=c or ctx(), params=params)[0]


def test_jornada_cumprida():
    r = one(marks(MON, "08:00", "12:00", "13:00", "17:00"))
    assert (r.expected_minutes, r.worked_minutes, r.break_minutes) == (480, 480, 60)
    assert r.overtime_minutes == r.deficit_minutes == 0 and r.status == "ok" and r.steps


def test_tolerancia_de_5_minutos_por_marcacao_e_10_no_dia():
    r = one(marks(MON, "08:04", "12:00", "13:00", "17:05"))
    assert r.tolerance_applied and r.late_minutes == 0 and r.overtime_minutes == r.deficit_minutes == 0


def test_tolerancia_ultrapassada_conta_tudo():
    # 6 minutos de atraso: fora da tolerância por marcação, conta integralmente (Súmula 366).
    r = one(marks(MON, "08:06", "12:00", "13:00", "17:00"))
    assert not r.tolerance_applied and r.late_minutes == 6 and r.deficit_minutes == 6


def test_soma_diaria_acima_de_10_minutos():
    r = one(marks(MON, "07:55", "12:00", "13:00", "17:06"))
    assert not r.tolerance_applied and r.overtime_minutes == 11 and r.overtime_rate_percent == 50


def test_horas_extras_e_alerta_de_limite():
    r = one(marks(MON, "08:00", "12:00", "13:00", "20:00"))
    assert r.overtime_minutes == 180 and any("limite diário" in i for i in r.issues)


def test_intervalo_suprimido():
    r = one(marks(MON, "08:00", "12:00", "12:30", "16:30"))
    assert r.break_minutes == 30 and r.break_suppressed_minutes == 30
    assert r.deficit_minutes == 0  # trabalhou 8 h; o intervalo menor é tratado como supressão


def test_jornada_de_6_horas_exige_15_minutos():
    c = ctx("08:00", "14:00", 0)
    assert one(marks(MON, "08:00", "14:00"), c).break_suppressed_minutes == 15  # 6 h: não supera 6 h
    assert one(marks(MON, "08:00", "11:00", "11:15", "14:15"), c).break_suppressed_minutes == 0
    assert one(marks(MON, "08:00", "14:15"), c).break_suppressed_minutes == 60  # passou de 6 h


def test_marcacoes_impares_ficam_inconsistentes():
    r = one(marks(MON, "08:00", "12:00", "13:00"))
    assert r.status == "inconsistent" and r.worked_minutes == 240 and r.deficit_minutes == 0


def test_falta_em_dia_previsto():
    r = one([])
    assert r.status == "absent" and r.deficit_minutes == 480


def test_folga_e_feriado_contam_a_100():
    sat = MON + dt.timedelta(days=5)
    r = one(marks(sat, "09:00", "13:00"), day=sat)
    assert r.expected_minutes == 0 and r.overtime_minutes == 240 and r.overtime_rate_percent == 100
    r = one(marks(MON, "08:00", "12:00"), ctx(holidays={MON: "Feriado municipal"}))
    assert r.holiday and r.overtime_minutes == 240 and r.overtime_rate_percent == 100


def test_turno_noturno_cruza_a_meia_noite():
    c = ctx("22:00", "06:00", 60)
    r = one(marks(MON, "22:00", "+02:00", "+03:00", "+06:00"), c)
    assert r.date == MON and r.worked_minutes == 420 and r.overtime_minutes == 0
    # 22:00–02:00 e 03:00–05:00 são noturnos (6 h de relógio); 6 h * 60/52,5 = 411 min.
    assert r.night_minutes == 360 and r.night_reduced_minutes == 411
    # Dia seguinte não recebe as marcações da madrugada.
    tue = compute_period(start=MON, end=MON + dt.timedelta(days=1), marks=r.marks, ctx=c, params=P)[1]
    assert tue.status == "absent"


def test_prorrogacao_noturna_opcional():
    c = ctx("22:00", "06:00", 60)
    m = marks(MON, "22:00", "+02:00", "+03:00", "+07:00")
    assert one(m, c).night_minutes == 360
    params = validate_params({"night_extension": True})
    assert one(m, c, params=params).night_minutes == 360 + 120


def test_chegada_antes_da_meia_noite_para_turno_da_madrugada():
    c = ctx("00:10", "06:10", 0, weekdays=range(7))
    tue = MON + dt.timedelta(days=1)
    r = compute_period(start=MON, end=tue, marks=marks(MON, "23:58", "+06:10"), ctx=c, params=P)
    assert r[0].status == "absent" and r[1].worked_minutes == 372 and r[1].tolerance_applied is False


def test_descanso_entre_jornadas():
    tue = MON + dt.timedelta(days=1)
    m = marks(MON, "08:00", "12:00", "13:00", "23:00") + marks(tue, "08:00", "12:00", "13:00", "17:00")
    r = compute_period(start=MON, end=tue, marks=m, ctx=ctx(), params=P)
    assert r[1].rest_violation_minutes == 120 and r[0].rest_violation_minutes == 0


def test_marcacao_repetida_por_toque_duplo():
    m = marks(MON, "08:00", "08:01", "12:00", "13:00", "17:00")
    r = one(m)
    assert r.status == "ok" and len(r.ignored_marks) == 1 and any("desconsiderada" in s for s in r.steps)


def test_horario_de_verao_nao_quebra_o_calculo():
    # Fuso com horário de verão (Nova York, 2026-11-01): jornada medida em instantes reais.
    ny = ZoneInfo("America/New_York")
    day = dt.date(2026, 11, 1)
    planned = SimpleNamespace(start_time=dt.time(0, 0), end_time=dt.time(4, 0), break_minutes=0)
    c = EmployeeContext(tz=ny, schedule_for=lambda d: planned)
    m = [Mark(dt.datetime(2026, 11, 1, 0, 0, tzinfo=ny)), Mark(dt.datetime(2026, 11, 1, 4, 0, tzinfo=ny))]
    r = compute_period(
        start=day, end=day, marks=m, ctx=c, params=validate_params({"night_reduced_hour": False})
    )[0]
    assert r.worked_minutes == 300  # 5 h reais (uma hora repetida)


def test_totais():
    tue = MON + dt.timedelta(days=1)
    m = marks(MON, "08:00", "12:00", "13:00", "18:00")
    t = totals(compute_period(start=MON, end=tue, marks=m, ctx=ctx(), params=P))
    assert t["overtime_by_rate"] == {"50": 60} and t["deficit_minutes"] == 480 and t["absences"] == 1
    assert t["balance_minutes"] == -420


@pytest.mark.parametrize(
    "bad",
    [
        {"tolerance_per_mark_minutes": -1},
        {"tolerance_per_mark_minutes": True},
        {"night_start": "25:00"},
        {"break_rules": [{"x": 1}]},
        {"desconhecido": 1},
        {"night_extension": "sim"},
    ],
)
def test_parametros_invalidos(bad):
    with pytest.raises(ValueError):
        validate_params(bad)


def test_padroes_tem_referencia():
    from apps.attendance.calculation import DEFAULT_PARAMS_REFS

    assert set(DEFAULT_PARAMS) - set(DEFAULT_PARAMS_REFS) <= {"night_end"}


def test_jornada_futura_ou_em_andamento_nao_e_falta():
    now = at(MON, "10:00")
    r = compute_period(
        start=MON, end=MON + dt.timedelta(days=1), marks=marks(MON, "08:00"), ctx=ctx(), params=P, now=now
    )
    assert r[0].status == "in_progress" and not r[0].issues and r[0].deficit_minutes == 0
    assert r[1].status == "upcoming" and r[1].deficit_minutes == 0
    # Sem `now` (fechamento de período passado) o comportamento continua o mesmo.
    assert compute_period(start=MON, end=MON, marks=[], ctx=ctx(), params=P)[0].status == "absent"
