import type { DayResult, RulesInfo } from "../api/attendance";

/** Janela do período noturno vinda das regras configuradas (HH:MM). */
export interface NightWindow {
  start: string;
  end: string;
}

/**
 * Regras vigentes no dia: a versão mais recente com início até a data; sem versão, o padrão do
 * sistema. Devolve `null` quando as regras não foram carregadas (nada é inventado).
 */
export function nightFor(rules: RulesInfo | null, date: string): NightWindow | null {
  if (!rules) return null;
  const version = [...rules.versions]
    .filter((v) => v.valid_from <= date)
    .sort((a, b) => (a.valid_from < b.valid_from ? 1 : -1))[0];
  const params = (version?.params ?? rules.defaults) as Record<string, unknown>;
  const { night_start: start, night_end: end } = params;
  return typeof start === "string" && typeof end === "string" ? { start, end } : null;
}

const toHours = (hhmm: string) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h + m / 60;
};

/**
 * Linha do tempo do dia (no fuso da unidade). Cada elemento tem forma ou padrão próprio além da cor:
 * - contorno tracejado: jornada prevista;
 * - barra cheia: período trabalhado (somente entre registros pareados);
 * - listras diagonais: intervalo entre dois períodos;
 * - pontilhado: horário noturno, conforme as regras da empresa;
 * - círculo: registro original; losango: registro incluído por ajuste;
 * - círculo tracejado: registro sem par (pendência — nenhum período é inventado).
 * Jornadas que cruzam a meia-noite estendem a escala para 30 h.
 */
export function DayRuler({ day, night }: { day: DayResult; night?: NightWindow | null }) {
  const span = spanHours(day);
  const hour = (local: string) => {
    const [d, t] = local.split(" ");
    const [h, m] = t.split(":").map(Number);
    const extra = d > day.date ? 24 : d < day.date ? -24 : 0;
    return h + extra + m / 60;
  };
  const pct = (h: number) => clamp((h / span) * 100);
  const hours = day.marks.map((m) => hour(m.local));
  const complete = Math.floor(day.marks.length / 2);
  const worked = Array.from({ length: complete }, (_, i) => [hours[i * 2], hours[i * 2 + 1]]);
  const gaps = worked.slice(1).map((w, i) => [worked[i][1], w[0]]);
  const planned = day.planned ? [hour(day.planned.start_local), hour(day.planned.end_local)] : null;
  const bands = night ? nightBands(toHours(night.start), toHours(night.end), span) : [];
  const label = describe(day);
  const incomplete = day.marks.length % 2 === 1;
  return (
    <div className="ruler" role="img" aria-label={label} title={label}>
      {bands.map(([a, b], i) => (
        <span
          key={i}
          className="night"
          style={{ left: `${pct(a)}%`, width: `${pct(b) - pct(a)}%` }}
        />
      ))}
      {planned && (
        <span
          className="planned"
          style={{ left: `${pct(planned[0])}%`, width: `${pct(planned[1]) - pct(planned[0])}%` }}
        />
      )}
      {gaps.map(([a, b], i) => (
        <span
          key={`g${i}`}
          className="gap"
          style={{ left: `${pct(a)}%`, width: `${pct(b) - pct(a)}%` }}
        />
      ))}
      {worked.map(([a, b], i) => (
        <span
          key={`w${i}`}
          className="worked"
          style={{ left: `${pct(a)}%`, width: `${Math.max(pct(b) - pct(a), 0.6)}%` }}
        />
      ))}
      {day.marks.map((m, i) => (
        <span
          key={m.at}
          className={
            incomplete && i === day.marks.length - 1
              ? "pin pending"
              : m.origin === "included"
                ? "pin included"
                : "pin"
          }
          style={{ left: `${pct(hours[i])}%` }}
        />
      ))}
    </div>
  );
}

/** Faixas [início, fim] em horas, dentro da escala, para um período que pode cruzar a meia-noite. */
function nightBands(start: number, end: number, span: number): [number, number][] {
  const raw: [number, number][] =
    start > end
      ? [
          [0, end],
          [start, 24 + end],
        ]
      : [
          [start, end],
          [24 + start, 24 + end],
        ];
  return raw
    .map(([a, b]) => [Math.min(a, span), Math.min(b, span)] as [number, number])
    .filter(([a, b]) => b > a);
}

export function RulerScale({ hours = 24 }: { hours?: number }) {
  const ticks = [0, 6, 12, 18, 24, ...(hours > 24 ? [30] : [])];
  return (
    <div className="ruler-scale" aria-hidden="true">
      {ticks.map((t) => (
        <span key={t}>{String(t % 24).padStart(2, "0")}h</span>
      ))}
    </div>
  );
}

export function Legend({ night }: { night: boolean }) {
  return (
    <div className="legend" aria-label="Legenda da linha do tempo">
      <span>
        <i className="l-worked" /> Trabalhado
      </span>
      <span>
        <i className="l-planned" /> Previsto
      </span>
      <span>
        <i className="l-gap" /> Intervalo
      </span>
      {night && (
        <span>
          <i className="l-night" /> Horário noturno
        </span>
      )}
      <span>
        <i className="l-pin" /> Registro original
      </span>
      <span>
        <i className="l-adjust" /> Incluído por ajuste
      </span>
      <span>
        <i className="l-pending" /> Registro sem par
      </span>
    </div>
  );
}

function clamp(v: number) {
  return Math.max(0, Math.min(100, v));
}

export function spanHours(day: DayResult): number {
  const last = day.marks[day.marks.length - 1];
  const crosses =
    (last && last.local.slice(0, 10) > day.date) ||
    (day.planned && day.planned.end_local.slice(0, 10) > day.date);
  return crosses ? 30 : 24;
}

function describe(day: DayResult): string {
  if (!day.marks.length) return "Sem registros";
  const marks = day.marks.map((m) => m.local.slice(11)).join(", ");
  return `Registros: ${marks}${day.marks.length % 2 ? ". Falta o par do último registro" : ""}`;
}
