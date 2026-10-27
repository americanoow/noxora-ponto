import { useState } from "react";
import {
  type DayResult,
  JUSTIFICATION_KINDS,
  type NewRequest,
  type Timesheet,
  createRequest,
  getTimesheet,
} from "../api/attendance";
import { downloads } from "../api/operational";
import { dateBR, dateTimeBR, dayLabel, hm, isoDate, monthRange } from "../lib/format";
import { useRouter } from "../lib/router";
import { useCompany } from "../lib/session";
import { useAction, useTask } from "../lib/task";
import { DayRuler, RulerScale } from "../ui/DayRuler";
import { Icon } from "../ui/icons";
import {
  Badge,
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

const STATUS: Record<string, [string, "tint" | "amber" | "seal" | undefined]> = {
  ok: ["Cumprida", "tint"],
  inconsistent: ["Inconsistente", "seal"],
  absent: ["Falta", "seal"],
  day_off: ["Folga", undefined],
  justified: ["Abonada", "amber"],
  upcoming: ["Prevista", undefined],
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
  const { companyId } = useCompany();
  const router = useRouter();
  const month = monthRange(isoDate(new Date()));
  const period = { from: from ?? month.from, to: to ?? month.to };
  const update = (p: Partial<{ employeeId: number; from: string; to: string }>) =>
    router.replaceTop({ screen: "timesheet", employeeId, ...period, ...p });
  const sheet = useTask(
    async () => (employeeId ? getTimesheet(companyId, employeeId, period.from, period.to) : null),
    [companyId, employeeId, period.from, period.to],
  );

  return (
    <Screen
      title="Espelho de ponto"
      subtitle={
        sheet.data
          ? `${sheet.data.employee.name}, matrícula ${sheet.data.employee.registration}`
          : undefined
      }
      toolbar={
        <>
          <EmployeePicker value={employeeId} onChange={(id) => update({ employeeId: id })} />
          <PeriodPicker
            from={period.from}
            to={period.to}
            onChange={(f, t) => update({ from: f, to: t })}
          />
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
                CSV
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
              O espelho mostra, dia a dia, as marcações, o previsto, as horas extras e como cada
              valor foi calculado.
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
          onRequest={(body) => createRequest(companyId, sheet.data!.employee.id, body)}
          onChanged={sheet.reload}
        />
      ) : null}
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
        aria-label="Início do período"
        value={from}
        onChange={(e) => e.target.value && onChange(e.target.value, to)}
      />
      <input
        type="date"
        aria-label="Fim do período"
        value={to}
        onChange={(e) => e.target.value && onChange(from, e.target.value)}
      />
    </span>
  );
}

/** Corpo compartilhado pelo espelho do gestor e pelo do funcionário. */
export function TimesheetBody({
  sheet,
  onRequest,
  onChanged,
}: {
  sheet: Timesheet;
  onRequest: (body: NewRequest) => Promise<unknown>;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [requestFor, setRequestFor] = useState<DayResult | null>(null);
  const t = sheet.totals;
  const closed = sheet.closings.filter((c) => c.status === "closed");
  const overtime = Object.entries(t.overtime_by_rate)
    .map(([rate, m]) => `${hm(m)} a ${rate}%`)
    .join(", ");
  const crosses = sheet.days.some((d) => d.marks.some((m) => m.local.slice(0, 10) > d.date));

  return (
    <>
      {closed.map((c) => (
        <p key={c.id} role={c.divergent ? "alert" : "status"} className="notice">
          Período de {dateBR(c.start)} a {dateBR(c.end)} fechado em {dateTimeBR(c.closed_at)}.
          {c.divergent &&
            " Chegaram marcações depois do fechamento: o espelho atual difere do fechado."}
        </p>
      ))}
      <Stats>
        <Stat label="Previsto" figure={hm(t.expected_minutes)} />
        <Stat label="Trabalhado" figure={hm(t.worked_minutes)} />
        <Stat
          label="Extras"
          figure={overtime || "00:00"}
          tone={t.overtime_minutes ? "tint" : undefined}
        />
        <Stat
          label="Débito"
          figure={hm(t.deficit_minutes)}
          tone={t.deficit_minutes ? "seal" : undefined}
        />
        <Stat
          label="Saldo"
          figure={hm(t.balance_minutes)}
          tone={t.balance_minutes < 0 ? "seal" : "tint"}
        />
        <Stat
          label="Dias com ocorrência"
          figure={t.days_with_issues}
          tone={t.days_with_issues ? "amber" : undefined}
        />
      </Stats>

      <Group
        title="Dias"
        aside={`Regras ${sheet.rule_versions.map((v) => `v${v.version}`).join(", ")}, fuso ${sheet.timezone}`}
        footer={
          <div className="legend">
            <span>
              <i style={{ background: "var(--tint)" }} />
              Trabalhado
            </span>
            <span>
              <i style={{ border: "1.5px dashed var(--ink-2)" }} />
              Previsto
            </span>
            <span>
              <i style={{ background: "var(--night-soft)" }} />
              Faixa noturna
            </span>
            <span>
              <i style={{ borderLeft: "2px dotted var(--amber)", width: 2 }} />
              Incluída por ajuste
            </span>
          </div>
        }
      >
        <div
          className="day-row"
          aria-hidden="true"
          style={{ cursor: "default", paddingTop: 6, paddingBottom: 0 }}
        >
          <span />
          <RulerScale hours={crosses ? 30 : 24} />
          <span className="num hide-sm" style={{ fontSize: 12, color: "var(--ink-3)" }}>
            Trab.
          </span>
          <span className="num hide-sm" style={{ fontSize: 12, color: "var(--ink-3)" }}>
            Saldo
          </span>
          <span />
          <span />
        </div>
        {sheet.days.map((day) => {
          const [label, tone] = STATUS[day.status];
          const balance = day.overtime_minutes - day.deficit_minutes;
          const expanded = open === day.date;
          return (
            <div key={day.date}>
              <button
                className="day-row"
                aria-expanded={expanded}
                onClick={() => setOpen(expanded ? null : day.date)}
              >
                <span className="date">
                  {dayLabel(day.date)}
                  {day.holiday && <small>{day.holiday}</small>}
                </span>
                <DayRuler day={day} />
                <span className="num hide-sm">
                  {day.marks.length ? hm(day.worked_minutes) : "—"}
                </span>
                <span className="num">{balance ? hm(balance) : "—"}</span>
                <span className="hide-sm">
                  {day.issues.length > 0 && day.status === "ok" ? (
                    <Badge tone="amber">Com ocorrência</Badge>
                  ) : (
                    <Badge tone={tone}>{label}</Badge>
                  )}
                </span>
                <span className="chevron hide-sm">
                  <Icon name={expanded ? "chevronDown" : "chevronRight"} size={16} />
                </span>
              </button>
              {expanded && <DayDetail day={day} onRequest={() => setRequestFor(day)} />}
            </div>
          );
        })}
      </Group>
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

function DayDetail({ day, onRequest }: { day: DayResult; onRequest: () => void }) {
  return (
    <div className="day-detail">
      <div className="toolbar" style={{ marginTop: 8 }}>
        {day.marks.map((m) => (
          <Badge key={m.at} tone={m.origin === "included" ? "amber" : undefined}>
            {m.local.slice(11)}
            {m.origin === "included" ? " incluída" : ""}
          </Badge>
        ))}
        {day.night_minutes > 0 && (
          <Badge tone="night">
            Noturno {hm(day.night_minutes)} ({hm(day.night_reduced_minutes)} reduzidas)
          </Badge>
        )}
        {day.break_suppressed_minutes > 0 && (
          <Badge tone="seal">Intervalo suprimido {day.break_suppressed_minutes} min</Badge>
        )}
      </div>
      {day.issues.length > 0 && (
        <ul className="steps" style={{ color: "var(--seal)" }}>
          {day.issues.map((i) => (
            <li key={i}>{i}</li>
          ))}
        </ul>
      )}
      <details open>
        <summary style={{ fontSize: 13, color: "var(--ink-2)", cursor: "pointer" }}>
          Como calculamos
        </summary>
        <ol className="steps">
          {day.steps.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ol>
      </details>
      <button onClick={onRequest}>
        <Icon name="plus" size={16} /> Pedir ajuste ou abono
      </button>
    </div>
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
  const [record, setRecord] = useState<number | "">("");
  const [kind, setKind] = useState("medical");
  const [minutes, setMinutes] = useState("");
  const [reason, setReason] = useState("");
  const [doc, setDoc] = useState("");
  const { pending, error, run } = useAction();
  if (!day) return null;
  const originals = day.marks.filter((m) => m.record_id);
  const offset = day.marks[0] ? offsetOf(day.marks[0]) : null;

  const submit = () =>
    run(async () => {
      if (mode === "include") {
        const tz = offset ?? -new Date().getTimezoneOffset();
        const sign = tz >= 0 ? "+" : "-";
        const abs = Math.abs(tz);
        const iso = `${day.date}T${time}:00${sign}${String(Math.floor(abs / 60)).padStart(2, "0")}:${String(abs % 60).padStart(2, "0")}`;
        await onSubmit({ kind: "include", occurred_at: iso, reason });
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
    <Sheet title={`Pedido para ${dayLabel(day.date)}`} open={!!day} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        style={{ display: "grid", gap: 12 }}
      >
        <div className="segmented" role="group" aria-label="Tipo de pedido">
          {(
            [
              ["include", "Incluir marcação"],
              ["disregard", "Desconsiderar"],
              ["justification", "Abono"],
            ] as [Mode, string][]
          ).map(([k, l]) => (
            <button key={k} type="button" aria-pressed={mode === k} onClick={() => setMode(k)}>
              {l}
            </button>
          ))}
        </div>
        {mode === "include" && (
          <Field
            label="Horário esquecido"
            hint="No fuso da unidade. A marcação original não é alterada; o ajuste entra na apuração após aprovação."
          >
            <input type="time" value={time} onChange={(e) => setTime(e.target.value)} required />
          </Field>
        )}
        {mode === "disregard" && (
          <Field
            label="Marcação a desconsiderar"
            hint="Ela continua guardada no registro de ponto; só deixa de contar na apuração."
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
            <Field label="Motivo do abono">
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                {JUSTIFICATION_KINDS.map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Minutos (vazio = dia todo)">
              <input
                type="number"
                min={1}
                max={1440}
                value={minutes}
                onChange={(e) => setMinutes(e.target.value)}
              />
            </Field>
            <Field label="Documento (nº ou referência)">
              <input value={doc} onChange={(e) => setDoc(e.target.value)} maxLength={200} />
            </Field>
          </div>
        )}
        <Field label="Justificativa">
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
            Enviar pedido
          </button>
        </div>
      </form>
    </Sheet>
  );
}

/** Deslocamento do fuso da unidade (minutos) a partir de uma marcação: hora local − instante UTC. */
function offsetOf(m: { at: string; local: string }): number {
  return Math.round((Date.parse(`${m.local.replace(" ", "T")}:00Z`) - Date.parse(m.at)) / 60000);
}
