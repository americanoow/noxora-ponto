import { useEffect, useRef, useState } from "react";
import { getSummary, listRequests } from "../api/attendance";
import { AVAILABILITY_LABELS, type BoardGroup, getBoard } from "../api/operational";
import { addDays, agoLabel, hm, isoDate, timeBR } from "../lib/format";
import { useRouter } from "../lib/router";
import { useCompany } from "../lib/session";
import { useTask } from "../lib/task";
import { Icon } from "../ui/icons";
import { Badge, Dot, Empty, ErrorText, Group, Kpi, Loading, Row, Screen } from "../ui/kit";

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return now;
}

/** Relógio isolado: só ele renderiza a cada segundo. */
function LiveClock() {
  const now = useClock();
  return (
    <div>
      <div className="clock" aria-label="Hora atual">
        {now.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
      </div>
      <div style={{ color: "var(--ink-2)", marginTop: 6 }}>
        {now.toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" })}
      </div>
    </div>
  );
}

const TONE: Record<string, "tint" | "amber" | "seal" | undefined> = {
  available: "tint",
  busy: "amber",
  on_break: "amber",
  away: "amber",
  external: "amber",
  unavailable: "seal",
  unknown: undefined,
};

function TeamCard({ g, onOpen }: { g: BoardGroup; onOpen: () => void }) {
  const total = g.employees.length;
  const present = g.employees.filter((e) => e.punch_hint?.likely_present).length;
  const pct = total ? Math.round((present / total) * 100) : 0;
  const reported = Object.entries(g.counts).filter(([k, n]) => n > 0 && k !== "unknown");
  const unknown = g.counts.unknown ?? 0;
  return (
    <div className="team-card">
      <header>
        <h3>{g.sector?.name ?? "Sem setor"}</h3>
        <small>{g.unit?.name ?? "Sem unidade"}</small>
        <button className="plain" style={{ marginLeft: "auto" }} onClick={onOpen}>
          Abrir <Icon name="chevronRight" size={14} />
        </button>
      </header>
      <div className="rows">
        <div>
          <span className="k">
            <Dot state="on" /> Com entrada registrada
          </span>
          <span className="num">
            {present} de {total}
          </span>
          <span className="bar" aria-hidden="true">
            <span style={{ width: `${pct}%` }} />
          </span>
        </div>
        <div>
          <span className="k">
            <Dot state="hollow" /> Situação informada
          </span>
          {reported.length === 0 && <span style={{ color: "var(--ink-2)" }}>ninguém informou</span>}
          {reported.map(([k, n]) => (
            <Badge key={k} tone={TONE[k]}>
              {n} {AVAILABILITY_LABELS[k as keyof typeof AVAILABILITY_LABELS].toLowerCase()}
            </Badge>
          ))}
          {unknown > 0 && <Badge>{unknown} sem informação</Badge>}
          {g.stale > 0 && <Badge tone="amber">{g.stale} desatualizada(s)</Badge>}
        </div>
      </div>
    </div>
  );
}

export function TodayScreen() {
  const { companyId, companyName } = useCompany();
  const router = useRouter();
  const today = isoDate(new Date());
  const yesterday = addDays(today, -1);
  const board = useTask(() => getBoard(companyId), [companyId]);
  const pending = useTask(() => listRequests(companyId, "pending"), [companyId]);
  const week = useTask(
    () => getSummary(companyId, addDays(today, -6), yesterday),
    [companyId, today],
  );
  const attentionRef = useRef<HTMLDivElement>(null);

  const people = board.data?.groups.flatMap((g) => g.employees) ?? [];
  const present = people.filter((p) => p.punch_hint?.likely_present).length;
  const stale = people.filter((p) => p.freshness === "stale" || p.freshness === "expired").length;
  const attention = (week.data?.results ?? []).filter(
    (r) => r.totals.inconsistent_days || r.totals.absences,
  );
  const generated = board.data?.generated_at;
  const outdated =
    !!generated &&
    Date.now() - new Date(generated).getTime() > (board.data?.stale_after_minutes ?? 30) * 60000;
  const reload = () => {
    board.reload();
    pending.reload();
    week.reload();
  };

  return (
    <Screen
      title="Hoje"
      subtitle={companyName}
      toolbar={
        <button onClick={reload}>
          <Icon name="refresh" size={16} /> Atualizar
        </button>
      }
    >
      <div className="today-hero">
        <LiveClock />
        <div className="freshness" role="status">
          {board.data ? (
            <>
              <Dot state={outdated ? "warn" : "on"} />
              Atualizado às <span className="num">{timeBR(generated)}</span> ({agoLabel(generated)})
              {outdated && <Badge tone="amber">Pode estar desatualizado</Badge>}
            </>
          ) : (
            "Carregando dados…"
          )}
        </div>
      </div>

      <div className="kpis">
        <Kpi
          label="Com entrada registrada"
          dot="on"
          figure={board.data ? `${present} de ${people.length}` : "—"}
          hint="Estimado pelos registros de ponto. Não confirma presença."
          tone="tint"
          onClick={() => router.select({ screen: "records" })}
        />
        <Kpi
          label="Solicitações aguardando"
          figure={pending.data?.length ?? "—"}
          hint="Ajustes e justificativas para responder."
          tone={pending.data?.length ? "amber" : undefined}
          onClick={() => router.select({ screen: "requests" })}
        />
        <Kpi
          label="Pessoas para revisar"
          figure={week.data ? attention.length : "—"}
          hint="Pessoas com falta ou registro incompleto nos últimos 7 dias."
          tone={attention.length ? "seal" : undefined}
          onClick={() => attentionRef.current?.scrollIntoView({ behavior: "smooth" })}
        />
        <Kpi
          label="Situações desatualizadas"
          figure={board.data ? stale : "—"}
          hint="Disponibilidade informada há muito tempo."
          tone={stale ? "amber" : undefined}
          onClick={() => router.select({ screen: "availability" })}
        />
      </div>

      <div className="two-col">
        <div>
          <Group
            title="Solicitações aguardando"
            aside={
              pending.data?.length ? (
                <button className="plain" onClick={() => router.select({ screen: "requests" })}>
                  Ver todas
                </button>
              ) : undefined
            }
          >
            {pending.loading && !pending.data ? (
              <Loading />
            ) : pending.error ? (
              <ErrorText message={pending.error} />
            ) : pending.data && pending.data.length ? (
              pending.data
                .slice(0, 5)
                .map((r) => (
                  <Row
                    key={`${r.type}-${r.id}`}
                    title={r.employee.name}
                    subtitle={`${r.kind_label}: ${r.reason}`}
                    accessory={<Badge tone="amber">Aguardando</Badge>}
                    onClick={() => router.select({ screen: "requests" })}
                  />
                ))
            ) : (
              <Empty title="Nenhuma solicitação aguardando" />
            )}
          </Group>

          <div ref={attentionRef}>
            <Group
              title="Para revisar nos últimos 7 dias"
              footer="Faltas e dias em que falta um registro. Abra a folha de ponto para ver o dia."
            >
              {week.loading && !week.data ? (
                <Loading />
              ) : week.error ? (
                <ErrorText message={week.error} />
              ) : attention.length ? (
                attention.slice(0, 8).map((r) => (
                  <Row
                    key={r.employee.id}
                    title={r.employee.name}
                    subtitle={`Matrícula ${r.employee.registration} · saldo ${hm(r.totals.balance_minutes)}`}
                    accessory={
                      <span className="toolbar">
                        {r.totals.absences > 0 && (
                          <Badge tone="seal">{r.totals.absences} falta(s)</Badge>
                        )}
                        {r.totals.inconsistent_days > 0 && (
                          <Badge tone="amber">{r.totals.inconsistent_days} incompleto(s)</Badge>
                        )}
                      </span>
                    }
                    onClick={() =>
                      router.push({
                        screen: "timesheet",
                        employeeId: r.employee.id,
                        from: addDays(today, -6),
                        to: yesterday,
                      })
                    }
                  />
                ))
              ) : (
                <Empty title="Tudo em ordem nos últimos 7 dias" />
              )}
            </Group>
          </div>
        </div>

        <Group
          title="Equipe por setor"
          footer={
            <>
              <Dot state="on" /> vem dos registros de ponto (estimativa das últimas 16 horas).{" "}
              <Dot state="hollow" /> é o que a equipe ou o gestor informou, com data e hora.
            </>
          }
        >
          {board.loading && !board.data ? (
            <Loading />
          ) : board.error ? (
            <ErrorText message={board.error} />
          ) : board.data && board.data.groups.length ? (
            board.data.groups.map((g) => (
              <TeamCard
                key={`${g.unit?.id}-${g.sector?.id}`}
                g={g}
                onOpen={() => router.select({ screen: "availability" })}
              />
            ))
          ) : (
            <Empty title="Nenhuma equipe sob a sua responsabilidade" />
          )}
        </Group>
      </div>
    </Screen>
  );
}
