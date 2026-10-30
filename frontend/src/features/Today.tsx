import { useEffect, useState } from "react";
import { getSummary, listRequests } from "../api/attendance";
import { AVAILABILITY_LABELS, getBoard } from "../api/operational";
import { addDays, hm, isoDate } from "../lib/format";
import { useRouter } from "../lib/router";
import { useCompany } from "../lib/session";
import { useTask } from "../lib/task";
import { Badge, Empty, ErrorText, Group, Loading, Row, Screen, Stat, Stats } from "../ui/kit";

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return now;
}

/** Relógio isolado: só ele renderiza a cada segundo (subview pequena, como recomenda a skill). */
function LiveClock() {
  const now = useClock();
  return (
    <div>
      <div className="clock" aria-label="Hora atual">
        {now.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
      </div>
      <div style={{ color: "var(--ink-2)" }}>
        {now.toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" })}
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

  const people = board.data?.groups.flatMap((g) => g.employees) ?? [];
  const present = people.filter((p) => p.punch_hint?.likely_present).length;
  const stale = people.filter((p) => p.freshness === "stale").length;
  const attention = (week.data?.results ?? [])
    .filter((r) => r.totals.inconsistent_days || r.totals.absences)
    .slice(0, 8);

  return (
    <Screen title="Hoje" subtitle={companyName}>
      <div className="today-hero">
        <LiveClock />
      </div>
      <Stats>
        <Stat
          label="Trabalhando agora (pelo ponto)"
          figure={board.data ? `${present} de ${people.length}` : "—"}
          tone="tint"
        />
        <Stat
          label="Pedidos aguardando decisão"
          figure={pending.data?.length ?? "—"}
          tone={pending.data?.length ? "amber" : undefined}
        />
        <Stat
          label="Situações sem atualização"
          figure={board.data ? stale : "—"}
          tone={stale ? "amber" : undefined}
        />
      </Stats>

      <Group
        title="Pedidos aguardando decisão"
        aside={
          pending.data?.length ? (
            <button className="plain" onClick={() => router.select({ screen: "requests" })}>
              Ver todos
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
          <Empty title="Nenhum pedido aguardando resposta" />
        )}
      </Group>

      <Group
        title="Últimos 7 dias: quem precisa da sua atenção"
        footer="Faltas e dias em que falta uma batida (por exemplo, entrou e não registrou a saída). Toque para abrir a folha de ponto."
      >
        {week.loading && !week.data ? (
          <Loading />
        ) : week.error ? (
          <ErrorText message={week.error} />
        ) : attention.length ? (
          attention.map((r) => (
            <Row
              key={r.employee.id}
              title={r.employee.name}
              subtitle={`Matrícula ${r.employee.registration}`}
              value={`saldo de horas ${hm(r.totals.balance_minutes)}`}
              accessory={
                <span className="toolbar">
                  {r.totals.absences > 0 && <Badge tone="seal">{r.totals.absences} falta(s)</Badge>}
                  {r.totals.inconsistent_days > 0 && (
                    <Badge tone="amber">{r.totals.inconsistent_days} dia(s) para revisar</Badge>
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

      <Group title="Como estão as equipes agora" footer={board.data?.notice}>
        {board.loading && !board.data ? (
          <Loading />
        ) : board.error ? (
          <ErrorText message={board.error} />
        ) : board.data && board.data.groups.length ? (
          board.data.groups.map((g) => (
            <Row
              key={`${g.unit?.id}-${g.sector?.id}`}
              title={g.unit?.name ?? "Sem unidade"}
              subtitle={g.sector?.name ?? "Sem setor"}
              accessory={
                <span className="toolbar">
                  {Object.entries(g.counts)
                    .filter(([, n]) => n > 0)
                    .map(([k, n]) => (
                      <Badge
                        key={k}
                        tone={k === "available" ? "tint" : k === "unknown" ? undefined : "amber"}
                      >
                        {n}{" "}
                        {AVAILABILITY_LABELS[k as keyof typeof AVAILABILITY_LABELS].toLowerCase()}
                      </Badge>
                    ))}
                </span>
              }
              onClick={() => router.select({ screen: "availability" })}
            />
          ))
        ) : (
          <Empty title="Nenhuma equipe sob a sua responsabilidade" />
        )}
      </Group>
    </Screen>
  );
}
