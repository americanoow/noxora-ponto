"""Motor de apuração da jornada: funções puras, sem banco, com explicação de cada passo.

Entrada: marcações efetivas (originais menos desconsideradas, mais inclusões aprovadas), jornada prevista,
feriados e o conjunto de regras vigente. Saída: um resultado por dia com totais e a lista de passos que
explica o cálculo. Nada aqui altera marcação; o resultado é derivado e pode ser recalculado.

Os parâmetros padrão seguem a leitura usual da CLT (referências em `DEFAULT_PARAMS_REFS`), mas são
**hipóteses de desenvolvimento a conferir com especialista**: convenções coletivas e acordos alteram
tolerâncias, adicionais, intervalos e compensação. Cada empresa tem regras versionadas por vigência.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, replace
from zoneinfo import ZoneInfo

RULES_ENGINE_VERSION = "apuracao-v2"

DEFAULT_PARAMS = {
    "tolerance_per_mark_minutes": 5,
    "tolerance_daily_minutes": 10,
    "overtime_rate_percent": 50,
    "rest_day_overtime_rate_percent": 100,
    "night_start": "22:00",
    "night_end": "05:00",
    "night_additional_percent": 20,
    "night_reduced_hour": True,
    "night_extension": False,
    "break_rules": [
        {"worked_over_minutes": 360, "min_break_minutes": 60},
        {"worked_over_minutes": 240, "min_break_minutes": 15},
    ],
    "min_rest_between_journeys_hours": 11,
    "max_daily_overtime_minutes": 120,
    "journey_split_gap_hours": 8,
    "journey_max_open_hours": 16,
    "duplicate_mark_window_seconds": 120,
}

DEFAULT_PARAMS_REFS = {
    "tolerance_per_mark_minutes": "CLT art. 58, §1º (variações de até 5 min por marcação)",
    "tolerance_daily_minutes": "CLT art. 58, §1º (limite de 10 min diários); Súmula 366 do TST",
    "overtime_rate_percent": "CLT art. 59, §1º / CF art. 7º, XVI (mínimo de 50%)",
    "rest_day_overtime_rate_percent": "Lei 605/1949; Súmula 146 do TST (dobra em repouso/feriado) — hipótese",
    "night_start": "CLT art. 73, §2º (22h às 5h, trabalhador urbano)",
    "night_additional_percent": "CLT art. 73, caput (adicional de 20%, urbano)",
    "night_reduced_hour": "CLT art. 73, §1º (hora noturna de 52 min 30 s)",
    "night_extension": "CLT art. 73, §5º; Súmula 60, II, do TST (prorrogação) — desligado por padrão",
    "break_rules": "CLT art. 71, caput e §1º; supressão indenizada (art. 71, §4º)",
    "min_rest_between_journeys_hours": "CLT art. 66 (11 h entre jornadas)",
    "max_daily_overtime_minutes": "CLT art. 59, caput (até 2 h extras diárias) — alerta, não bloqueia",
    "journey_split_gap_hours": "Parâmetro técnico do produto (separação de jornadas)",
    "journey_max_open_hours": "Parâmetro técnico do produto (duração máxima de jornada sem saída registrada)",
    "duplicate_mark_window_seconds": "Parâmetro técnico do produto (toque duplo no terminal)",
}


def validate_params(params: dict) -> dict:
    """Mescla com o padrão e valida tipos/limites. Levanta ValueError com mensagem em português."""
    merged = {**DEFAULT_PARAMS, **(params or {})}
    unknown = set(merged) - set(DEFAULT_PARAMS)
    if unknown:
        raise ValueError(f"Parâmetros desconhecidos: {', '.join(sorted(unknown))}.")
    # Limites mínimos da lei (convenção ou acordo só podem melhorar para o trabalhador): tolerância de até
    # 5 min por marcação e 10 min por dia (CLT art. 58, §1º; Súmula 449 do TST), hora extra com adicional de
    # pelo menos 50% (CF art. 7º, XVI), adicional noturno de pelo menos 20% (CLT art. 73) e alerta de
    # descanso entre jornadas a partir de 11 h (CLT art. 66). Valores menores esconderiam direitos.
    ints = {
        "tolerance_per_mark_minutes": (0, 5),
        "tolerance_daily_minutes": (0, 10),
        "overtime_rate_percent": (50, 500),
        "rest_day_overtime_rate_percent": (100, 500),
        "night_additional_percent": (20, 500),
        "min_rest_between_journeys_hours": (11, 48),
        "max_daily_overtime_minutes": (0, 1440),
        "journey_split_gap_hours": (2, 24),
        "journey_max_open_hours": (2, 48),
        "duplicate_mark_window_seconds": (0, 3600),
    }
    for key, (low, high) in ints.items():
        value = merged[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"{key}: informe um inteiro entre {low} e {high}.")
    for key in ("night_reduced_hour", "night_extension"):
        if not isinstance(merged[key], bool):
            raise ValueError(f"{key}: informe verdadeiro ou falso.")
    for key in ("night_start", "night_end"):
        try:
            dt.time.fromisoformat(merged[key])
        except (TypeError, ValueError):
            raise ValueError(f"{key}: use HH:MM.") from None
    rules = merged["break_rules"]
    if not isinstance(rules, list) or len(rules) > 5:
        raise ValueError("break_rules: lista de até 5 regras.")
    for rule in rules:
        if (
            not isinstance(rule, dict)
            or set(rule) != {"worked_over_minutes", "min_break_minutes"}
            or not all(
                isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 1440 for v in rule.values()
            )
        ):
            raise ValueError("break_rules: cada regra tem worked_over_minutes e min_break_minutes (minutos).")
    # Intervalo mínimo (CLT art. 71): 15 min acima de 4 h e, acima de 6 h, 1 h (redutível a 30 min só por
    # convenção ou acordo coletivo, art. 611-A, III). As regras não podem exigir menos que isso.
    for worked, legal in ((241, 15), (361, 30)):
        required = max(
            (r["min_break_minutes"] for r in rules if worked > r["worked_over_minutes"]), default=0
        )
        if required < legal:
            raise ValueError(
                f"break_rules: acima de {worked - 1} min trabalhados o intervalo mínimo é de {legal} min "
                "(CLT art. 71; abaixo de 1 h, só com convenção ou acordo coletivo)."
            )
    return merged


@dataclass(frozen=True)
class Mark:
    at: dt.datetime  # instante (com fuso)
    record_id: int | None = None
    origin: str = "original"  # original | included (inclusão aprovada, etapa 9)
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlannedDay:
    """Jornada prevista de um dia. `end` pode ser no dia seguinte (turno que cruza a meia-noite)."""

    start: dt.datetime
    end: dt.datetime
    break_minutes: int

    @property
    def expected_minutes(self) -> int:
        return max(0, int((self.end - self.start).total_seconds() // 60) - self.break_minutes)


@dataclass
class DayResult:
    date: dt.date
    planned: PlannedDay | None
    holiday: str = ""
    marks: list[Mark] = field(default_factory=list)
    expected_minutes: int = 0
    worked_minutes: int = 0
    break_minutes: int = 0
    late_minutes: int = 0
    early_leave_minutes: int = 0
    overtime_minutes: int = 0
    overtime_rate_percent: int = 0
    deficit_minutes: int = 0
    night_minutes: int = 0
    night_reduced_minutes: int = 0
    break_suppressed_minutes: int = 0
    rest_violation_minutes: int = 0
    justified_minutes: int = 0
    tolerance_applied: bool = False
    status: str = "ok"  # ok | inconsistent | absent | day_off | justified | upcoming | in_progress
    issues: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    ignored_marks: list[Mark] = field(default_factory=list)
    tz: ZoneInfo | None = None

    def _local(self, moment: dt.datetime) -> str:
        return (moment.astimezone(self.tz) if self.tz else moment).strftime("%Y-%m-%d %H:%M")

    def as_dict(self) -> dict:
        def mark(m: Mark) -> dict:
            local = m.at.astimezone(self.tz) if self.tz else m.at
            return {
                "at": m.at.isoformat(),
                "local": local.strftime("%Y-%m-%d %H:%M"),
                "record_id": m.record_id,
                "origin": m.origin,
                "flags": list(m.flags),
            }

        return {
            "date": self.date.isoformat(),
            "holiday": self.holiday,
            "planned": (
                {
                    "start": self.planned.start.isoformat(),
                    "end": self.planned.end.isoformat(),
                    "start_local": self._local(self.planned.start),
                    "end_local": self._local(self.planned.end),
                    "break_minutes": self.planned.break_minutes,
                }
                if self.planned
                else None
            ),
            "marks": [mark(m) for m in self.marks],
            "ignored_marks": [mark(m) for m in self.ignored_marks],
            "expected_minutes": self.expected_minutes,
            "worked_minutes": self.worked_minutes,
            "break_minutes": self.break_minutes,
            "late_minutes": self.late_minutes,
            "early_leave_minutes": self.early_leave_minutes,
            "overtime_minutes": self.overtime_minutes,
            "overtime_rate_percent": self.overtime_rate_percent,
            "deficit_minutes": self.deficit_minutes,
            "night_minutes": self.night_minutes,
            "night_reduced_minutes": self.night_reduced_minutes,
            "break_suppressed_minutes": self.break_suppressed_minutes,
            "rest_violation_minutes": self.rest_violation_minutes,
            "justified_minutes": self.justified_minutes,
            "tolerance_applied": self.tolerance_applied,
            "status": self.status,
            "timezone": str(self.tz) if self.tz else "",
            "issues": list(self.issues),
            "steps": list(self.steps),
        }


def _minutes(delta: dt.timedelta) -> int:
    return int(delta.total_seconds() // 60)


def _hm(minutes: int) -> str:
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def _clock(moment: dt.datetime, tz: ZoneInfo) -> str:
    return moment.astimezone(tz).strftime("%d/%m %H:%M")


def dedupe_marks(marks: list[Mark], window_seconds: int) -> tuple[list[Mark], list[Mark]]:
    """Marcações em sequência dentro da janela (toque duplo) contam uma vez; as outras ficam visíveis."""
    kept, ignored = [], []
    for m in sorted(marks, key=lambda x: x.at):
        if kept and window_seconds and (m.at - kept[-1].at).total_seconds() < window_seconds:
            ignored.append(m)
        else:
            kept.append(m)
    return kept, ignored


# Folga máxima, depois do fim previsto do turno, para um registro ainda ser a saída dele.
PLANNED_OVERRUN = dt.timedelta(hours=4)


def _shift_for(first: dt.datetime, tz: ZoneInfo, planned_for):
    """Turno que contém o primeiro registro (de 6 h antes do início até o fim + `PLANNED_OVERRUN`).

    Devolve `(turno, houve_turno_no_dia)`: o segundo valor distingue um registro solto fora de qualquer
    turno (dia com jornada, mas registro longe dela) de um dia sem jornada prevista (folga).
    """
    local = first.astimezone(tz).date()
    any_planned = planned_for(local) is not None
    best, best_gap = None, None
    for candidate in (local - dt.timedelta(days=1), local, local + dt.timedelta(days=1)):
        planned = planned_for(candidate)
        if planned is None:
            continue
        if planned.start - dt.timedelta(hours=6) <= first <= planned.end + PLANNED_OVERRUN:
            gap = abs((planned.start - first).total_seconds())
            if best_gap is None or gap < best_gap:
                best, best_gap = planned, gap
    return best, any_planned


def split_journeys(
    marks: list[Mark],
    gap_hours: int,
    max_open_hours: int | None = None,
    *,
    tz_at=None,
    planned_for=None,
) -> list[list[Mark]]:
    """Separa as marcações em jornadas.

    - Jornada **fechada** (número par de registros): o próximo registro só continua a jornada se vier
      antes de `gap_hours` (volta de intervalo); depois disso começa outra jornada.
    - Jornada **aberta** (entrada sem saída): o próximo registro é tratado como a saída enquanto vier em
      até `max_open_hours` e, havendo turno previsto, até o fim dele mais `PLANNED_OVERRUN`. Assim um
      turno de 12 h ou noturno (19h–7h) não é cortado ao meio, e uma saída esquecida não engole a entrada
      do dia seguinte. Registro solto fora de qualquer turno usa só `gap_hours`.
    """
    max_open = dt.timedelta(hours=max_open_hours if max_open_hours else gap_hours)
    journeys: list[list[Mark]] = []
    for m in sorted(marks, key=lambda x: x.at):
        if journeys:
            current = journeys[-1]
            gap = m.at - current[-1].at
            if len(current) % 2 == 0:
                joins = gap < dt.timedelta(hours=gap_hours)
            else:
                joins = gap < max_open
                if joins and planned_for is not None and tz_at is not None:
                    shift, any_planned = _shift_for(current[0].at, tz_at(current[0].at), planned_for)
                    if shift is not None:
                        joins = m.at <= shift.end + PLANNED_OVERRUN
                    elif any_planned:
                        joins = gap < dt.timedelta(hours=gap_hours)
            if joins:
                current.append(m)
                continue
        journeys.append([m])
    return journeys


def journey_date(journey: list[Mark], tz: ZoneInfo, planned_for) -> dt.date:
    """Data de referência: a do primeiro registro, salvo se o início previsto do dia seguinte
    estiver mais perto (quem chega 23:50 para um turno das 00:10 pertence ao dia seguinte)."""
    first = journey[0].at
    local = first.astimezone(tz).date()
    best, best_gap = local, None
    for candidate in (local, local + dt.timedelta(days=1)):
        planned = planned_for(candidate)
        if planned is None:
            continue
        gap = abs((planned.start - first).total_seconds())
        if gap <= 6 * 3600 and (best_gap is None or gap < best_gap):
            best, best_gap = candidate, gap
    return best


def _night_minutes(start: dt.datetime, end: dt.datetime, tz: ZoneInfo, params: dict) -> int:
    """Minutos do intervalo [start, end) dentro da faixa noturna local (pode cruzar a meia-noite)."""
    night_start = dt.time.fromisoformat(params["night_start"])
    night_end = dt.time.fromisoformat(params["night_end"])
    total = 0
    local_start = start.astimezone(tz)
    day = local_start.date() - dt.timedelta(days=1)
    while True:
        window_start = dt.datetime.combine(day, night_start, tzinfo=tz)
        end_day = day + dt.timedelta(days=1) if night_end <= night_start else day
        window_end = dt.datetime.combine(end_day, night_end, tzinfo=tz)
        if window_start >= end:
            break
        overlap = min(end, window_end).astimezone(dt.UTC) - max(start, window_start).astimezone(dt.UTC)
        if overlap.total_seconds() > 0:
            total += _minutes(overlap)
        day += dt.timedelta(days=1)
    return total


def compute_day(
    *,
    date: dt.date,
    tz: ZoneInfo,
    planned: PlannedDay | None,
    marks: list[Mark],
    params: dict,
    holiday: str = "",
    previous_journey_end: dt.datetime | None = None,
    ignored: list[Mark] | None = None,
    now: dt.datetime | None = None,
) -> DayResult:
    r = DayResult(date=date, planned=planned, holiday=holiday, marks=sorted(marks, key=lambda m: m.at), tz=tz)
    r.ignored_marks = list(ignored or [])
    steps = r.steps
    rest_day = planned is None or bool(holiday)
    r.expected_minutes = 0 if rest_day else planned.expected_minutes
    if planned:
        steps.append(
            f"Jornada prevista: {_clock(planned.start, tz)} a {_clock(planned.end, tz)}, intervalo de "
            f"{planned.break_minutes} min = {_hm(planned.expected_minutes)}."
        )
    else:
        steps.append("Sem jornada prevista neste dia (folga/descanso).")
    if holiday:
        steps.append(f"Feriado: {holiday}. Horas trabalhadas contam como extras de repouso/feriado.")
    for m in r.ignored_marks:
        steps.append(
            f"Marcação de {_clock(m.at, tz)} desconsiderada: repetida em menos de "
            f"{params['duplicate_mark_window_seconds']} s (continua guardada no registro original)."
        )
    for m in r.marks:
        if m.origin == "included":
            steps.append(f"Marcação de {_clock(m.at, tz)} incluída por ajuste aprovado.")

    if not r.marks and now is not None and planned is not None and not rest_day and planned.end > now:
        # Jornada ainda não terminou (hoje ou futuro): não é falta.
        r.status = "upcoming"
        steps.append("Jornada ainda não terminou: sem saldo a apurar.")
        return r
    if not r.marks:
        if rest_day:
            r.status = "day_off"
            steps.append("Sem marcações: nada a apurar.")
        else:
            r.status = "absent"
            r.deficit_minutes = r.expected_minutes
            r.issues.append("Sem marcações em dia de trabalho previsto (falta ou ajuste pendente).")
            steps.append(f"Ausência: {_hm(r.deficit_minutes)} não trabalhadas.")
        return r

    if len(r.marks) % 2:
        r.status = "inconsistent"
        r.issues.append("Número ímpar de marcações: a última não tem par (ajuste pendente).")
        steps.append("Número ímpar de marcações: só os pares completos foram somados.")

    pairs = [(r.marks[i], r.marks[i + 1]) for i in range(0, len(r.marks) - 1, 2)]
    worked = sum(_minutes(b.at - a.at) for a, b in pairs)
    breaks = sum(_minutes(pairs[i + 1][0].at - pairs[i][1].at) for i in range(len(pairs) - 1))
    for a, b in pairs:
        steps.append(
            f"Período trabalhado: {_clock(a.at, tz)} a {_clock(b.at, tz)} = {_hm(_minutes(b.at - a.at))}."
        )
    r.worked_minutes, r.break_minutes = worked, breaks
    steps.append(f"Total trabalhado: {_hm(worked)}; intervalos: {_hm(breaks)}.")

    # Intervalo intrajornada mínimo (art. 71): a regra mais exigente cuja carga foi superada.
    for rule in sorted(params["break_rules"], key=lambda x: -x["worked_over_minutes"]):
        if worked > rule["worked_over_minutes"]:
            if pairs and breaks < rule["min_break_minutes"]:
                r.break_suppressed_minutes = rule["min_break_minutes"] - breaks
                r.issues.append(
                    f"Intervalo de {breaks} min, abaixo do mínimo de {rule['min_break_minutes']} min "
                    f"para mais de {rule['worked_over_minutes'] // 60} h trabalhadas."
                )
                steps.append(
                    f"Intervalo suprimido: {r.break_suppressed_minutes} min (indenização a apurar na folha)."
                )
            break

    # Faixa noturna.
    if params["night_reduced_hour"] or params["night_additional_percent"]:
        night = sum(_night_minutes(a.at, b.at, tz, params) for a, b in pairs)
        if night and params["night_extension"] and pairs:
            # Prorrogação (Súmula 60, II, do TST — conferir com a política da empresa): se a jornada começou
            # dentro da faixa noturna, todo o trabalho depois do fim da faixa também é noturno, em qualquer
            # período da jornada (intervalos não a interrompem). Considera TODOS os períodos, não só o último.
            first_start = pairs[0][0].at
            if _night_minutes(first_start, first_start + dt.timedelta(minutes=1), tz, params):
                night_end = dt.time.fromisoformat(params["night_end"])
                local_start = first_start.astimezone(tz)
                boundary_local = dt.datetime.combine(local_start.date(), night_end, tzinfo=tz)
                if boundary_local <= local_start:
                    boundary_local = dt.datetime.combine(
                        local_start.date() + dt.timedelta(days=1), night_end, tzinfo=tz
                    )
                boundary = boundary_local.astimezone(dt.UTC)
                extra = sum(_minutes(b.at - max(a.at, boundary)) for a, b in pairs if b.at > boundary)
                if extra > 0:
                    night += extra
                    steps.append(f"Prorrogação do horário noturno: +{_hm(extra)} após {params['night_end']}.")
        r.night_minutes = night
        if night:
            r.night_reduced_minutes = round(night * 60 / 52.5) if params["night_reduced_hour"] else night
            steps.append(
                f"Horas noturnas ({params['night_start']}–{params['night_end']}): {_hm(night)} de relógio"
                + (
                    f" = {_hm(r.night_reduced_minutes)} em hora reduzida"
                    if params["night_reduced_hour"]
                    else ""
                )
                + f"; adicional de {params['night_additional_percent']}%."
            )

    # Descanso entre jornadas (art. 66).
    if previous_journey_end is not None:
        rest = _minutes(r.marks[0].at - previous_journey_end)
        minimum = params["min_rest_between_journeys_hours"] * 60
        if 0 <= rest < minimum:
            r.rest_violation_minutes = minimum - rest
            r.issues.append(f"Descanso entre jornadas de {_hm(rest)}, abaixo de {_hm(minimum)}.")
            steps.append(f"Interjornada insuficiente: faltaram {_hm(r.rest_violation_minutes)}.")

    if rest_day:
        r.overtime_minutes = worked
        r.overtime_rate_percent = params["rest_day_overtime_rate_percent"]
        if worked:
            steps.append(f"Trabalho em folga/feriado: {_hm(worked)} extras a {r.overtime_rate_percent}%.")
        return r
    if r.status == "inconsistent":
        if now is not None and planned.end > now:
            r.status = "in_progress"
            r.issues.remove("Número ímpar de marcações: a última não tem par (ajuste pendente).")
            steps.append("Jornada em andamento: saldo apurado ao fim do dia.")
        else:
            steps.append("Saldo não calculado até o ajuste das marcações.")
        return r

    # Atrasos e saídas antecipadas (entrada/saída) e tolerância do art. 58, §1º.
    first, last = r.marks[0].at, r.marks[-1].at
    late = max(0, _minutes(first - planned.start))
    early_in = max(0, _minutes(planned.start - first))
    early_out = max(0, _minutes(planned.end - last))
    late_out = max(0, _minutes(last - planned.end))
    variations = [late or early_in, early_out or late_out]
    per_mark, daily = params["tolerance_per_mark_minutes"], params["tolerance_daily_minutes"]
    if all(v <= per_mark for v in variations) and sum(variations) <= daily:
        r.tolerance_applied = True
        effective = worked + late + early_out - early_in - late_out
        steps.append(
            f"Variações de entrada/saída ({variations[0]} e {variations[1]} min) dentro da tolerância "
            f"({per_mark} min por marcação, {daily} min no dia): desconsideradas."
        )
    else:
        effective = worked
        r.late_minutes, r.early_leave_minutes = late, early_out
        if late or early_out or early_in or late_out:
            steps.append(
                f"Variações fora da tolerância: entrada {'+' if early_in else '-'}{early_in or late} min, "
                f"saída {'+' if late_out else '-'}{late_out or early_out} min; contadas integralmente."
            )
    balance = effective - r.expected_minutes
    if balance > 0:
        r.overtime_minutes = balance
        r.overtime_rate_percent = params["overtime_rate_percent"]
        steps.append(f"Saldo positivo: {_hm(balance)} extras a {r.overtime_rate_percent}%.")
        if balance > params["max_daily_overtime_minutes"]:
            r.issues.append(
                f"Horas extras acima do limite diário de {_hm(params['max_daily_overtime_minutes'])}."
            )
    elif balance < 0:
        r.deficit_minutes = -balance
        steps.append(f"Saldo negativo: {_hm(-balance)} (atrasos, saídas antecipadas ou intervalo maior).")
    else:
        steps.append("Saldo zero: jornada cumprida.")
    return r


@dataclass
class EmployeeContext:
    """Como montar a jornada prevista de cada data para um funcionário.

    `tz_for(date)` devolve o fuso da lotação vigente na data (uma transferência entre unidades de fusos
    diferentes não desloca o passado). Sem ele, vale `tz` em todo o período.
    """

    tz: ZoneInfo
    schedule_for: callable  # (date) -> ScheduleDay-like | None
    holiday_for: callable = lambda d: ""  # noqa: E731
    tz_for: callable | None = None  # (date) -> ZoneInfo

    def tz_on(self, date: dt.date) -> ZoneInfo:
        return self.tz_for(date) if self.tz_for else self.tz

    def tz_at(self, instant: dt.datetime) -> ZoneInfo:
        return self.tz_on(instant.astimezone(dt.UTC).date())

    def planned(self, date: dt.date) -> PlannedDay | None:
        day = self.schedule_for(date)
        if day is None:
            return None
        tz = self.tz_on(date)
        start = dt.datetime.combine(date, day.start_time, tzinfo=tz)
        end_date = date + dt.timedelta(days=1) if day.end_time <= day.start_time else date
        end = dt.datetime.combine(end_date, day.end_time, tzinfo=tz)
        # Em UTC: a subtração entre horários do mesmo fuso em Python ignora o horário de verão.
        return PlannedDay(
            start=start.astimezone(dt.UTC), end=end.astimezone(dt.UTC), break_minutes=day.break_minutes
        )


def compute_period(
    *,
    start: dt.date,
    end: dt.date,
    marks: list[Mark],
    ctx: EmployeeContext,
    params: dict,
    now: dt.datetime | None = None,
) -> list[DayResult]:
    """Apura cada dia de [start, end]. Marcações fora do período são usadas só para agrupar jornadas e
    medir o descanso entre jornadas."""
    marks = [replace(m, at=m.at.astimezone(dt.UTC)) for m in marks]
    kept, ignored = dedupe_marks(marks, params["duplicate_mark_window_seconds"])
    journeys = split_journeys(
        kept,
        params["journey_split_gap_hours"],
        params["journey_max_open_hours"],
        tz_at=ctx.tz_at,
        planned_for=ctx.planned,
    )
    by_date: dict[dt.date, list[list[Mark]]] = {}
    for journey in journeys:
        by_date.setdefault(journey_date(journey, ctx.tz_at(journey[0].at), ctx.planned), []).append(journey)
    ignored_by_date: dict[dt.date, list[Mark]] = {}
    for m in ignored:
        ignored_by_date.setdefault(m.at.astimezone(ctx.tz_at(m.at)).date(), []).append(m)

    results = []
    previous_end = None
    ordered_dates = sorted(by_date)
    for d in ordered_dates:
        if d < start:
            previous_end = by_date[d][-1][-1].at
    day = start
    while day <= end:
        day_journeys = by_date.get(day, [])
        day_marks = [m for j in day_journeys for m in j]
        result = compute_day(
            date=day,
            tz=ctx.tz_on(day),
            planned=ctx.planned(day),
            marks=day_marks,
            params=params,
            holiday=ctx.holiday_for(day),
            previous_journey_end=previous_end,
            ignored=ignored_by_date.get(day),
            now=now,
        )
        if len(day_journeys) > 1:
            result.issues.append("Mais de uma jornada no mesmo dia: conferir.")
        results.append(result)
        if day_marks:
            previous_end = day_marks[-1].at
        day += dt.timedelta(days=1)
    return results


def totals(results: list[DayResult]) -> dict:
    keys = (
        "expected_minutes",
        "worked_minutes",
        "late_minutes",
        "early_leave_minutes",
        "deficit_minutes",
        "night_minutes",
        "night_reduced_minutes",
        "break_suppressed_minutes",
        "justified_minutes",
    )
    out = {k: sum(getattr(r, k) for r in results) for k in keys}
    out["overtime_by_rate"] = {}
    for r in results:
        if r.overtime_minutes:
            key = str(r.overtime_rate_percent)
            out["overtime_by_rate"][key] = out["overtime_by_rate"].get(key, 0) + r.overtime_minutes
    out["overtime_minutes"] = sum(out["overtime_by_rate"].values())
    out["balance_minutes"] = out["overtime_minutes"] - out["deficit_minutes"]
    out["days_with_issues"] = sum(1 for r in results if r.issues)
    out["absences"] = sum(1 for r in results if r.status == "absent")
    out["inconsistent_days"] = sum(1 for r in results if r.status == "inconsistent")
    return out
