import { useState } from "react";
import {
  type DayResult,
  JUSTIFICATION_KINDS,
  type NewRequest,
  type RulesInfo,
  type Timesheet,
  createRequest,
  getRules,
  getTimesheet,
} from "../api/attendance";
import { downloads } from "../api/operational";
import { dateBR, dateTimeBR, dayLabel, hm, isoDate, monthRange } from "../lib/format";
import { useRouter } from "../lib/router";
import { useCompany } from "../lib/session";
import { useAction, useTask } from "../lib/task";
import {
  DayRuler,
  Legend,
  type NightWindow,
  RulerScale,
  nightFor,
  spanHours,
} from "../ui/DayRuler";
import { Icon } from "../ui/icons";
import {
  Badge,
  Dot,
  Download,
  Empty,
  ErrorText,
  Field,
  Group,
  Loading,
  Screen,
  Sheet,
  Stat,
  Stats,
} from "../ui/kit";
import { EmployeePicker } from "./EmployeePicker";
import { HourBankSection } from "./HourBank";

const STATUS: Record<string, [string, "tint" | "amber" | "seal" | undefined]> = {
  ok: ["Em dia", "tint"],
  inconsistent: ["Registro incompleto", "amber"],
  absent: ["Falta", "seal"],
  day_off: ["Folga", undefined],
  justified: ["Justificado", "amber"],
  upcoming: ["Ainda não chegou", undefined],
  in_progress: ["Em andamento", "tint"],
};

export function TimesheetScreen({
  employeeId,
  from,
  to,
}: {
  employeeId?: number;
  from?: string;
  to?: string;
}) {
  const { companyId, isAdmin } = useCompany();
  const router = useRouter();
  const month = monthRange(isoDate(new Date()));
  const period = { from: from ?? month.from, to: to ?? month.to };
  const update = (p: Partial<{ employeeId: number; from: string; to: string }>) =>
    router.replaceTop({ screen: "timesheet", employeeId, ...period, ...p });
  const sheet = useTask(
    async () => (employeeId ? getTimesheet(companyId, employeeId, period.from, period.to) : null),
    [companyId, employeeId, period.from, period.to],
  );
  // As regras (horário noturno) só entram na linha do tempo quando o sistema as entrega.
  const rules = useTask(() => getRules(companyId).catch(() => null), [companyId]);

  return (
    <Screen
      title="Folha de ponto"
      subtitle={
        sheet.data
          ? `${sheet.data.employee.name}, matrícula ${sheet.data.employee.registration}`
          : "Confira os horários, os totais e as ocorrências de cada dia."
      }
      toolbar={
        <>
          <EmployeePicker value={employeeId} onChange={(id) => update({ employeeId: id })} />
          <PeriodPicker
            from={period.from}
            to={period.to}
            onChange={(f, t) => update({ from: f, to: t })}
          />
          <Download href={downloads.summary(companyId, period.from, period.to)}>
            Resumo da equipe (planilha)
          </Download>
          {employeeId && (
            <>
              <Download
                href={downloads.timesheet(companyId, employeeId, period.from, period.to, "pdf")}
              >
                PDF
              </Download>
              <Download
                href={downloads.timesheet(companyId, employeeId, period.from, period.to, "csv")}
              >
                Planilha
              </Download>
            </>
          )}
        </>
      }
    >
      {!employeeId ? (
        <Group>
          <Empty title="Escolha um funcionário">
            <p>
              A folha de ponto mostra, dia a dia, os registros, as horas a cumprir, as horas extras
              e como cada valor foi calculado.
            </p>
          </Empty>
        </Group>
      ) : sheet.loading && !sheet.data ? (
        <Loading />
      ) : sheet.error ? (
        <ErrorText message={sheet.error} />
      ) : sheet.data ? (
        <TimesheetBody
          sheet={sheet.data}
          rules={rules.data ?? null}
          onRequest={(body) => createRequest(companyId, sheet.data!.employee.id, body)}
          onChanged={sheet.reload}
        />
      ) : null}
      {employeeId && (
        <HourBankSection companyId={companyId} employeeId={employeeId} canEdit={isAdmin} />
      )}
    </Screen>
  );
}

export function PeriodPicker({
  from,
  to,
  onChange,
}: {
  from: string;
  to: string;
  onChange: (from: string, to: string) => void;
}) {
  return (
    <span className="toolbar">
      <input
        type="date"
        aria-label="Primeiro dia do período"
        value={from}
        onChange={(e) => e.target.value && onChange(e.target.value, to)}
      />
      <input
        type="date"
        aria-label="Último dia do período"
        value={to}
        onChange={(e) => e.target.value && onChange(from, e.target.value)}
      />
    </span>
  );
}

/** Horários do dia em texto exato: pares "entrada → saída"; o último sem par vira pendência. */
function timesText(day: DayResult) {
  if (!day.marks.length) return "—";
  const parts: React.ReactNode[] = [];
  for (let i = 0; i < day.marks.length; i += 2) {
    const a = day.marks[i];
    const b = day.marks[i + 1];
    parts.push(
      <span key={a.at}>
        {i > 0 && " · "}
        {a.local.slice(11)} → {b ? b.local.slice(11) : <em>falta o par</em>}
      </span>,
    );
  }
  return parts;
}

/** Corpo compartilhado pela folha do gestor e pela do funcionário. */
export function TimesheetBody({
  sheet,
  rules = null,
  onRequest,
  onChanged,
}: {
  sheet: Timesheet;
  rules?: RulesInfo | null;
  onRequest: (body: NewRequest) => Promise<unknown>;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState<DayResult | null>(null);
  const [requestFor, setRequestFor] = useState<DayResult | null>(null);
  const t = sheet.totals;
  const closed = sheet.closings.filter((c) => c.status === "closed");
  const overtime = Object.entries(t.overtime_by_rate)
    .map(([rate, m]) => `${hm(m)} a ${rate}%`)
    .join(", ");
  const crosses = sheet.days.some((d) => spanHours(d) > 24);
  const hasNight = !!rules;

  return (
    <>
      {closed.map((c) => (
        <p key={c.id} role={c.divergent ? "alert" : "status"} className="notice">
          Período fechado de {dateBR(c.start)} a {dateBR(c.end)} em {dateTimeBR(c.closed_at)}.
          {c.divergent &&
            " Chegaram registros depois do fechamento: esta folha é diferente da versão fechada."}
        </p>
      ))}
      <Stats>
        <Stat label="Horas a cumprir" figure={hm(t.expected_minutes)} />
        <Stat label="Horas trabalhadas" figure={hm(t.worked_minutes)} />
        <Stat
          label="Horas extras"
          figure={overtime || "00:00"}
          tone={t.overtime_minutes ? "tint" : undefined}
        />
        <Stat
          label="Horas devidas"
          figure={hm(t.deficit_minutes)}
          tone={t.deficit_minutes ? "seal" : undefined}
        />
        <Stat
          label="Saldo do período"
          figure={hm(t.balance_minutes)}
          tone={t.balance_minutes < 0 ? "seal" : "tint"}
        />
        <Stat
          label="Dias para revisar"
          figure={t.days_with_issues}
          tone={t.days_with_issues ? "amber" : undefined}
        />
      </Stats>

      <Group title="Dias" footer={<Legend night={hasNight} />}>
        <div className="table-head" aria-hidden="true">
          <span>Dia</span>
          <span>
            Linha do tempo
            <RulerScale hours={crosses ? 30 : 24} />
          </span>
          <span className="times">Registros</span>
          <span className="num hide-sm">Trabalho</span>
          <span className="num">Saldo do dia</span>
          <span className="col-status hide-sm">Situação</span>
          <span />
        </div>
        {sheet.days.map((day) => {
          const [label, tone] = STATUS[day.status];
          const balance = day.overtime_minutes - day.deficit_minutes;
          const incomplete = day.marks.length % 2 === 1;
          return (
            <button
              key={day.date}
              className="day-row"
              aria-haspopup="dialog"
              onClick={() => setOpen(day)}
            >
              <span className="date">
                {dayLabel(day.date)}
                {day.holiday && <small>{day.holiday}</small>}
              </span>
              <DayRuler day={day} night={nightFor(rules, day.date)} />
              <span className="times">{timesText(day)}</span>
              <span className="num hide-sm">{day.marks.length ? hm(day.worked_minutes) : "—"}</span>
              <span className="num">{balance ? hm(balance) : "—"}</span>
              <span className="col-status hide-sm">
                {incomplete ? (
                  <Badge tone="amber">
                    <Dot state="hollow-warn" /> Pendência
                  </Badge>
                ) : day.issues.length > 0 && day.status === "ok" ? (
                  <Badge tone="amber">Revisar</Badge>
                ) : (
                  <Badge tone={tone}>{label}</Badge>
                )}
              </span>
              <span className="chevron">
                <Icon name="chevronRight" size={16} />
              </span>
            </button>
          );
        })}
      </Group>
      <DayPanel
        day={open}
        sheet={sheet}
        night={open ? nightFor(rules, open.date) : null}
        onClose={() => setOpen(null)}
        onRequest={() => {
          setRequestFor(open);
          setOpen(null);
        }}
      />
      <RequestSheet
        day={requestFor}
        onClose={() => setRequestFor(null)}
        onSubmit={async (body) => {
          await onRequest(body);
          setRequestFor(null);
          onChanged();
        }}
      />
    </>
  );
}

/** Painel do dia: registros (originais e ajustes), totais e a explicação do cálculo. */
function DayPanel({
  day,
  sheet,
  night,
  onClose,
  onRequest,
}: {
  day: DayResult | null;
  sheet: Timesheet;
  night: NightWindow | null;
  onClose: () => void;
  onRequest: () => void;
}) {
  const router = useRouter();
  if (!day) return null;
  const [label, tone] = STATUS[day.status];
  const incomplete = day.marks.length % 2 === 1;
  const rule = sheet.rule_versions.find((v) => v.from <= day.date && day.date <= v.to);
  const row = (k: string, v: string) => (
    <div className="row" style={{ padding: "8px 0", minHeight: 0 }}>
      <span className="title">{k}</span>
      <span className="value num">{v}</span>
    </div>
  );
  return (
    <Sheet
      title={`${dayLabel(day.date)} · Como chegamos a esse número`}
      open
      side
      onClose={onClose}
    >
      <div className="panel-section">
        <Badge tone={tone}>{label}</Badge> {day.holiday && <Badge>{day.holiday}</Badge>}
        <div style={{ marginTop: 12 }}>
          <DayRuler day={day} night={night} />
          <RulerScale hours={spanHours(day)} />
        </div>
      </div>

      <div className="panel-section">
        <h3>Registros do dia</h3>
        {day.marks.length === 0 && <p>Nenhum registro neste dia.</p>}
        <div className="toolbar">
          {day.marks.map((m) => (
            <span key={m.at} className={m.origin === "included" ? "chip-time adjust" : "chip-time"}>
              {m.local.slice(11)}
              <small style={{ fontWeight: 500 }}>
                {m.origin === "included" ? "ajuste aprovado" : "original"}
              </small>
            </span>
          ))}
          {day.ignored_marks.map((m) => (
            <span
              key={m.at}
              className="chip-time ignored"
              title="Desconsiderado por ajuste aprovado"
            >
              {m.local.slice(11)}
              <small style={{ fontWeight: 500 }}>desconsiderado</small>
            </span>
          ))}
        </div>
        {incomplete && (
          <p className="notice warn" style={{ marginTop: 12 }}>
            Falta o par do último registro. Esse período ficou fora da soma até haver um ajuste
            aprovado.
          </p>
        )}
        <p style={{ color: "var(--ink-2)", fontSize: "var(--text-sm)", marginTop: 8 }}>
          Os registros originais nunca são alterados. Ajustes aprovados aparecem à parte e podem ser
          consultados em Solicitações.
        </p>
      </div>

      <div className="panel-section">
        <h3>Totais do dia</h3>
        {day.planned &&
          row(
            "Jornada prevista",
            `${day.planned.start_local.slice(11)} – ${day.planned.end_local.slice(11)} (intervalo ${day.planned.break_minutes} min)`,
          )}
        {row("Horas a cumprir", hm(day.expected_minutes))}
        {row("Horas trabalhadas", day.marks.length ? hm(day.worked_minutes) : "—")}
        {row("Intervalo registrado", `${day.break_minutes} min`)}
        {day.overtime_minutes > 0 &&
          row("Horas extras", `${hm(day.overtime_minutes)} a ${day.overtime_rate_percent}%`)}
        {day.deficit_minutes > 0 && row("Horas devidas", hm(day.deficit_minutes))}
        {day.justified_minutes > 0 && row("Horas justificadas", hm(day.justified_minutes))}
        {day.night_minutes > 0 &&
          row(
            "Horas noturnas",
            `${hm(day.night_minutes)} (contam como ${hm(day.night_reduced_minutes)})`,
          )}
        {day.break_suppressed_minutes > 0 &&
          row("Intervalo não cumprido", `${day.break_suppressed_minutes} min`)}
      </div>

      <div className="panel-section">
        <h3>Como o sistema calculou</h3>
        <ol className="steps">
          {day.steps.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ol>
        {day.issues.length > 0 && (
          <ul className="steps" style={{ color: "var(--danger)" }}>
            {day.issues.map((i) => (
              <li key={i}>{i}</li>
            ))}
          </ul>
        )}
        {day.tolerance_applied && (
          <p style={{ color: "var(--ink-2)", fontSize: "var(--text-sm)" }}>
            A tolerância de minutos foi aplicada neste dia.
          </p>
        )}
        <details className="tech">
          <summary>Detalhes técnicos</summary>
          <p>
            Regras de cálculo {rule ? `versão ${rule.version}` : "padrão do sistema"}. Fuso da
            unidade: {day.timezone || sheet.timezone}. Versão do cálculo: {sheet.engine_version}.
          </p>
        </details>
      </div>

      <div className="actions" style={{ justifyContent: "flex-start" }}>
        <button className="primary" onClick={onRequest}>
          <Icon name="plus" size={16} /> Pedir ajuste
        </button>
        <button
          onClick={() => {
            onClose();
            router.select({ screen: "requests" });
          }}
        >
          Ver solicitações
        </button>
      </div>
    </Sheet>
  );
}

type Mode = "include" | "disregard" | "justification";

export function RequestSheet({
  day,
  onClose,
  onSubmit,
}: {
  day: DayResult | null;
  onClose: () => void;
  onSubmit: (body: NewRequest) => Promise<void>;
}) {
  const [mode, setMode] = useState<Mode>("include");
  const [time, setTime] = useState("17:00");
  // Turno noturno: a batida esquecida pode cair no dia seguinte ao da folha.
  const [nextDay, setNextDay] = useState(false);
  const [record, setRecord] = useState<number | "">("");
  const [kind, setKind] = useState("medical");
  const [minutes, setMinutes] = useState("");
  const [reason, setReason] = useState("");
  const [doc, setDoc] = useState("");
  const { pending, error, run } = useAction();
  if (!day) return null;
  const originals = day.marks.filter((m) => m.record_id);
  const nextDate = shiftDate(day.date, 1);
  const chosenDate = nextDay ? nextDate : day.date;

  const submit = () =>
    run(async () => {
      if (mode === "include") {
        // Data e hora da UNIDADE do funcionario, sem fuso: o servidor aplica o fuso da lotacao vigente
        // naquela data (nunca o do navegador de quem digita).
        await onSubmit({ kind: "include", occurred_local: `${chosenDate}T${time}`, reason });
      } else if (mode === "disregard") {
        await onSubmit({ kind: "disregard", record_id: Number(record), reason });
      } else {
        await onSubmit({
          type: "justification",
          date: day.date,
          kind,
          minutes: minutes ? Number(minutes) : null,
          reason,
          document_ref: doc,
        });
      }
    });

  return (
    <Sheet title={`Pedir ajuste · ${dayLabel(day.date)}`} open={!!day} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        style={{ display: "grid", gap: 12 }}
      >
        <div className="segmented" role="group" aria-label="O que você quer pedir">
          {(
            [
              ["include", "Esqueci de bater"],
              ["disregard", "Bati por engano"],
              ["justification", "Justificar ausência"],
            ] as [Mode, string][]
          ).map(([k, l]) => (
            <button key={k} type="button" aria-pressed={mode === k} onClick={() => setMode(k)}>
              {l}
            </button>
          ))}
        </div>
        {mode === "include" && (
          <>
            <Field
              label="Que horas você deveria ter batido?"
              hint={`A batida original não é alterada. O horário só passa a valer depois que o gestor aprovar. Vale o horário da unidade${day.timezone ? ` (${day.timezone})` : ""}.`}
            >
              <input type="time" value={time} onChange={(e) => setTime(e.target.value)} required />
            </Field>
            <label style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <input
                type="checkbox"
                checked={nextDay}
                onChange={(e) => setNextDay(e.target.checked)}
              />
              Foi na madrugada do dia seguinte ({dateBR(nextDate)})
            </label>
            <p className="muted">
              A batida será pedida para {dateBR(chosenDate)} às {time}.
            </p>
          </>
        )}
        {mode === "disregard" && (
          <Field
            label="Qual batida foi feita por engano?"
            hint="Ela continua guardada no histórico, mas deixa de contar nas horas depois da aprovação."
          >
            <select value={record} onChange={(e) => setRecord(Number(e.target.value))} required>
              <option value="">Escolha…</option>
              {originals.map((m) => (
                <option key={m.at} value={m.record_id!}>
                  {m.local.slice(11)}
                </option>
              ))}
            </select>
          </Field>
        )}
        {mode === "justification" && (
          <div className="form-grid">
            <Field label="Motivo da ausência">
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                {JUSTIFICATION_KINDS.map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Quantos minutos? (deixe vazio para o dia todo)">
              <input
                type="number"
                min={1}
                max={1440}
                value={minutes}
                onChange={(e) => setMinutes(e.target.value)}
              />
            </Field>
            <Field label="Documento que comprova (opcional)">
              <input value={doc} onChange={(e) => setDoc(e.target.value)} maxLength={200} />
            </Field>
          </div>
        )}
        <Field label="Explique o motivo" hint="Escreva pelo menos 5 letras.">
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            minLength={5}
            maxLength={500}
            required
          />
        </Field>
        <ErrorText message={error} />
        <div className="actions">
          <button type="submit" disabled={pending}>
            Enviar solicitação
          </button>
        </div>
      </form>
    </Sheet>
  );
}

/** Soma dias a uma data AAAA-MM-DD sem depender do fuso do navegador. */
function shiftDate(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}
