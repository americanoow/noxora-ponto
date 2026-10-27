import type { DayResult } from "../api/attendance";

/**
 * Régua do dia: 24 h do dia da jornada (no fuso da unidade), com a faixa noturna, o turno previsto
 * (contorno), os períodos trabalhados (faixa preenchida; aberta = sem par) e cada marcação como pino.
 * Turnos que cruzam a meia-noite se estendem até 30 h para não cortar a madrugada.
 */
export function DayRuler({ day }: { day: DayResult }) {
  const span = spanHours(day);
  const pos = (local: string) => {
    const [d, t] = local.split(" ");
    const [h, m] = t.split(":").map(Number);
    const extra = d > day.date ? 24 : d < day.date ? -24 : 0;
    return clamp(((h + extra + m / 60) / span) * 100);
  };
  const pairs: [number, number | null][] = [];
  for (let i = 0; i < day.marks.length; i += 2) {
    pairs.push([pos(day.marks[i].local), day.marks[i + 1] ? pos(day.marks[i + 1].local) : null]);
  }
  const planned = day.planned ? [pos(day.planned.start_local), pos(day.planned.end_local)] : null;
  const label = describe(day);
  return (
    <div className="ruler" role="img" aria-label={label} title={label}>
      <span className="night" style={{ left: 0, width: `${(5 / span) * 100}%` }} />
      <span
        className="night"
        style={{
          left: `${(22 / span) * 100}%`,
          width: `${((Math.min(span, 29) - 22) / span) * 100}%`,
        }}
      />
      {planned && (
        <span
          className="planned"
          style={{ left: `${planned[0]}%`, width: `${planned[1] - planned[0]}%` }}
        />
      )}
      {pairs.map(([a, b], i) => (
        <span
          key={i}
          className={b === null ? "worked open" : "worked"}
          style={{ left: `${a}%`, width: `${Math.max((b ?? Math.min(a + 4, 100)) - a, 0.6)}%` }}
        />
      ))}
      {day.marks.map((m) => (
        <span
          key={m.at}
          className={m.origin === "included" ? "pin included" : "pin"}
          style={{ left: `${pos(m.local)}%` }}
        />
      ))}
    </div>
  );
}

export function RulerScale({ hours = 24 }: { hours?: number }) {
  const ticks = [0, 6, 12, 18, hours];
  return (
    <div className="ruler-scale" aria-hidden="true">
      {ticks.map((t) => (
        <span key={t}>{String(t % 24).padStart(2, "0")}h</span>
      ))}
    </div>
  );
}

function clamp(v: number) {
  return Math.max(0, Math.min(100, v));
}

function spanHours(day: DayResult): number {
  const last = day.marks[day.marks.length - 1];
  const crosses =
    (last && last.local.slice(0, 10) > day.date) ||
    (day.planned && day.planned.end_local.slice(0, 10) > day.date);
  return crosses ? 30 : 24;
}

function describe(day: DayResult): string {
  const marks = day.marks.map((m) => m.local.slice(11)).join(", ");
  return marks ? `Marcações: ${marks}` : "Sem marcações";
}
