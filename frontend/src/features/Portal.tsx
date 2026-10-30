import { useState } from "react";
import {
  type AttendanceRequest,
  cancelMyRequest,
  createMyRequest,
  getMyTimesheet,
  listMyRequests,
} from "../api/attendance";
import {
  AVAILABILITY_LABELS,
  type AvailabilityStatus,
  acknowledgeClosing,
  downloads,
  getMyAvailability,
  listMyClosings,
  listMyPunches,
  setMyAvailability,
} from "../api/operational";
import { dateBR, dateTimeBR, hm, isoDate, monthRange } from "../lib/format";
import { useRouter } from "../lib/router";
import { useCompany } from "../lib/session";
import { usePaged } from "../lib/paged";
import { useAction, useTask } from "../lib/task";
import { KIND_LABELS, formatLocalTime } from "../timeclockApi";
import {
  Badge,
  Dot,
  Download,
  Empty,
  ErrorText,
  Field,
  Group,
  LoadMore,
  Loading,
  Row,
  Screen,
  Sheet,
} from "../ui/kit";
import { Icon } from "../ui/icons";
import { StatusPicker } from "./Availability";
import { STATUS_LABEL, describeRequest } from "./Requests";
import { HourBankSection } from "./HourBank";
import { PeriodPicker, TimesheetBody } from "./Timesheet";

export function MyDayScreen() {
  const { companyId } = useCompany();
  const router = useRouter();
  const punches = useTask(() => listMyPunches(companyId), [companyId]);
  // Sem registro a API responde vazio: normaliza para null.
  const availability = useTask(async () => {
    const current = await getMyAvailability(companyId);
    return current?.status ? current : null;
  }, [companyId]);
  const { error, run } = useAction();
  const today = isoDate(new Date());
  const all = [...(punches.data?.results ?? [])].sort((a, b) =>
    a.occurred_at < b.occurred_at ? -1 : 1,
  );
  const todays = all.filter((r) => r.occurred_local_date === today);
  const last = todays[todays.length - 1] ?? null;
  // Estimativa: soma os pares completos e, se houver registro aberto, conta até agora.
  let minutes = 0;
  for (let i = 0; i < todays.length; i += 2) {
    const a = new Date(todays[i].occurred_at).getTime();
    const b = todays[i + 1] ? new Date(todays[i + 1].occurred_at).getTime() : Date.now();
    minutes += Math.max(0, Math.round((b - a) / 60000));
  }
  const open = todays.length % 2 === 1;
  const hhmm = (r: (typeof all)[number]) =>
    formatLocalTime(r.occurred_at, r.occurred_offset_minutes).slice(11, 16);
  return (
    <Screen title="Hoje" subtitle="Seus registros de ponto e comprovantes.">
      <div className="hero-card" aria-live="polite">
        {punches.loading && !punches.data ? (
          <Loading />
        ) : punches.error ? (
          <ErrorText message={punches.error} />
        ) : last ? (
          <>
            <div style={{ color: "var(--ink-2)", display: "flex", gap: 8, alignItems: "center" }}>
              <Dot state={open ? "on" : undefined} />
              {open ? "Jornada em aberto" : "Último registro de hoje"}
            </div>
            <div className="last">
              {last.declared_kind ? `${KIND_LABELS[last.declared_kind]} às ` : "Registro às "}
              <span className="num">{hhmm(last)}</span>
            </div>
            <div className="est">
              {last.unit.name}
              {last.offline ? " · feito sem internet e enviado depois" : ""}
            </div>
            <div className="est">
              Cerca de <b className="num">{hm(minutes)}</b> trabalhadas hoje: <b>estimativa</b> a
              partir dos seus registros{open ? ", contando até agora" : ""}. O valor oficial está na
              folha de ponto.
            </div>
          </>
        ) : (
          <>
            <div className="last">Nenhum registro hoje</div>
            <div className="est">Quando você registrar o ponto no tablet, ele aparece aqui.</div>
          </>
        )}
      </div>

      <div className="quick">
        <button onClick={() => router.select({ screen: "my-timesheet" })}>
          <Icon name="sheet" size={22} /> Folha de ponto
        </button>
        <button onClick={() => router.select({ screen: "my-timesheet" })}>
          <Icon name="plus" size={22} /> Pedir ajuste
        </button>
        <button onClick={() => router.select({ screen: "my-closings" })}>
          <Icon name="lock" size={22} /> Meses fechados
        </button>
      </div>

      <Group
        title="Registros das últimas 48 horas"
        footer="O comprovante é um PDF informativo. O comprovante oficial com assinatura digital ainda não está disponível."
      >
        {punches.loading && !punches.data ? (
          <Loading />
        ) : all.length ? (
          <div className="group-body padded" style={{ border: 0, boxShadow: "none" }}>
            <ol className="tl">
              {[...all].reverse().map((r) => (
                <li key={r.id}>
                  <Dot state="on" />
                  <span>
                    <b className="num">
                      {formatLocalTime(r.occurred_at, r.occurred_offset_minutes).slice(0, 16)}
                    </b>
                    <small>
                      {r.declared_kind ? `${KIND_LABELS[r.declared_kind]} · ` : ""}
                      {r.unit.name} · registro nº {r.nsr}
                      {r.offline ? " · enviado depois (estava sem internet)" : ""}
                    </small>
                  </span>
                  <Download href={downloads.myReceipt(companyId, r.id)}>Comprovante</Download>
                </li>
              ))}
            </ol>
          </div>
        ) : (
          <Empty title="Nenhum registro nas últimas 48 horas" />
        )}
      </Group>

      <Group
        title="Como estou agora"
        padded
        footer="Serve para avisar a equipe. Isto não registra o seu ponto."
      >
        <p>
          Agora:{" "}
          <b>
            {availability.data ? AVAILABILITY_LABELS[availability.data.status] : "nada informado"}
          </b>
          {availability.data && ` (desde ${dateTimeBR(availability.data.set_at)})`}
        </p>
        <StatusPicker
          value={(availability.data?.status ?? "available") as AvailabilityStatus}
          onChange={(s) =>
            void run(async () => {
              await setMyAvailability(companyId, s);
              availability.reload();
            })
          }
        />
        <ErrorText message={error} />
      </Group>
    </Screen>
  );
}

export function MyTimesheetScreen() {
  const { companyId } = useCompany();
  const [period, setPeriod] = useState(monthRange(isoDate(new Date())));
  const sheet = useTask(
    () => getMyTimesheet(companyId, period.from, period.to),
    [companyId, period.from, period.to],
  );
  return (
    <Screen
      title="Minha folha de ponto"
      subtitle="Toque em um dia para ver os registros e como o cálculo foi feito."
      toolbar={
        <>
          <PeriodPicker
            from={period.from}
            to={period.to}
            onChange={(from, to) => setPeriod({ from, to })}
          />
          <Download href={downloads.myTimesheet(companyId, period.from, period.to)}>PDF</Download>
        </>
      }
    >
      {sheet.loading && !sheet.data ? (
        <Loading />
      ) : sheet.error ? (
        <ErrorText message={sheet.error} />
      ) : sheet.data ? (
        <TimesheetBody
          sheet={sheet.data}
          onRequest={(body) => createMyRequest(companyId, body)}
          onChanged={sheet.reload}
        />
      ) : null}
      <HourBankSection companyId={companyId} canEdit={false} mine />
    </Screen>
  );
}

export function MyRequestsScreen() {
  const { companyId } = useCompany();
  const router = useRouter();
  const list = usePaged((page) => listMyRequests(companyId, page), [companyId]);
  const { error, run } = useAction();
  return (
    <Screen
      title="Minhas solicitações"
      subtitle="Para pedir um ajuste, abra o dia na sua folha de ponto e toque em “Pedir ajuste”."
      toolbar={
        <button className="primary" onClick={() => router.select({ screen: "my-timesheet" })}>
          Abrir minha folha de ponto
        </button>
      }
    >
      <ErrorText message={error} />
      <Group>
        {list.loading && !list.ready ? (
          <Loading />
        ) : list.items.length ? (
          list.items.map((r: AttendanceRequest) => {
            const [label, tone] = STATUS_LABEL[r.status];
            return (
              <Row
                key={`${r.type}-${r.id}`}
                title={describeRequest(r)}
                subtitle={`${r.reason}${r.decision_note ? `. Resposta: ${r.decision_note}` : ""}`}
                accessory={
                  <span className="toolbar">
                    <Badge tone={tone}>{label}</Badge>
                    {r.status === "pending" && (
                      <button
                        className="plain"
                        onClick={() =>
                          void run(async () => {
                            await cancelMyRequest(companyId, r);
                            list.reload();
                          })
                        }
                      >
                        Cancelar
                      </button>
                    )}
                  </span>
                }
              />
            );
          })
        ) : (
          <Empty title="Você ainda não fez nenhuma solicitação" />
        )}
      </Group>
      <LoadMore
        shown={list.items.length}
        total={list.count}
        hasMore={list.hasMore}
        loading={list.loading}
        onMore={list.loadMore}
      />
    </Screen>
  );
}

export function MyClosingsScreen() {
  const { companyId } = useCompany();
  const list = useTask(() => listMyClosings(companyId), [companyId]);
  const [acking, setAcking] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const { pending, error, run } = useAction();
  return (
    <Screen
      title="Meses fechados"
      subtitle="Consulte cada período fechado. Você pode registrar ciência, sem que isso substitua um pedido de ajuste."
    >
      <Group>
        {list.loading && !list.data ? (
          <Loading />
        ) : list.data?.length ? (
          list.data.map((c) => (
            <Row
              key={c.id}
              title={`${dateBR(c.start)} a ${dateBR(c.end)}`}
              subtitle={
                c.acknowledged_at
                  ? `Ciência registrada em ${dateTimeBR(c.acknowledged_at)}`
                  : c.status === "reopened"
                    ? "Reabertura registrada pela empresa"
                    : undefined
              }
              accessory={
                <span className="toolbar">
                  <Download href={downloads.myTimesheet(companyId, c.start, c.end)}>
                    Folha de ponto
                  </Download>
                  {!c.acknowledged_at && c.status === "closed" && (
                    <button onClick={() => setAcking(c.id)}>Registrar ciência</button>
                  )}
                </span>
              }
            />
          ))
        ) : (
          <Empty title="Nenhum mês fechado ainda" />
        )}
      </Group>
      <Sheet
        title="Confirmar minha folha de ponto"
        open={acking !== null}
        onClose={() => setAcking(null)}
      >
        <p>
          Isto registra que você viu a folha deste período, com data e hora. Não é uma assinatura e
          não significa concordar com todos os valores. Se algo estiver errado, peça um ajuste.
        </p>
        <Field label="Quer deixar um comentário? (opcional)">
          <textarea value={comment} onChange={(e) => setComment(e.target.value)} maxLength={500} />
        </Field>
        <ErrorText message={error} />
        <div className="actions">
          <button
            className="primary"
            disabled={pending}
            onClick={() =>
              void run(async () => {
                await acknowledgeClosing(companyId, acking!, comment);
                setAcking(null);
                setComment("");
                list.reload();
              })
            }
          >
            Registrar ciência
          </button>
        </div>
      </Sheet>
    </Screen>
  );
}
