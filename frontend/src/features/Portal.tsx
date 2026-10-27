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
import { dateBR, dateTimeBR, isoDate, monthRange } from "../lib/format";
import { useRouter } from "../lib/router";
import { useCompany } from "../lib/session";
import { useAction, useTask } from "../lib/task";
import { formatLocalTime } from "../timeclockApi";
import {
  Badge,
  Download,
  Empty,
  ErrorText,
  Field,
  Group,
  Loading,
  Row,
  Screen,
  Sheet,
} from "../ui/kit";
import { StatusPicker } from "./Availability";
import { STATUS_LABEL, describeRequest } from "./Requests";
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
  return (
    <Screen title="Meu ponto" subtitle="Marcações das últimas 48 horas e comprovantes.">
      <Group
        title="Marcações recentes"
        footer="O comprovante oficial assinado (ICP-Brasil) ainda não está disponível; o PDF é informativo."
      >
        {punches.loading && !punches.data ? (
          <Loading />
        ) : punches.error ? (
          <ErrorText message={punches.error} />
        ) : punches.data?.results.length ? (
          punches.data.results.map((r) => (
            <Row
              key={r.id}
              title={formatLocalTime(r.occurred_at, r.occurred_offset_minutes)}
              subtitle={`${r.unit.name}, NSR ${r.nsr}${r.offline ? ", registrada sem conexão" : ""}`}
              accessory={
                <Download href={downloads.myReceipt(companyId, r.id)}>Comprovante</Download>
              }
            />
          ))
        ) : (
          <Empty title="Nenhuma marcação nas últimas 48 horas" />
        )}
      </Group>
      <Group
        title="Minha disponibilidade"
        padded
        footer="Informação para a equipe. Não registra ponto."
      >
        <p>
          Agora:{" "}
          {availability.data ? AVAILABILITY_LABELS[availability.data.status] : "sem informação"}
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
      <Group>
        <Row
          title="Ver meu espelho do mês"
          onClick={() => router.select({ screen: "my-timesheet" })}
        />
        <Row
          title="Pedir ajuste ou abono"
          onClick={() => router.select({ screen: "my-requests" })}
        />
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
      title="Meu espelho"
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
    </Screen>
  );
}

export function MyRequestsScreen() {
  const { companyId } = useCompany();
  const router = useRouter();
  const list = useTask(() => listMyRequests(companyId), [companyId]);
  const { error, run } = useAction();
  return (
    <Screen
      title="Meus pedidos"
      subtitle="Para pedir, abra o dia no seu espelho e toque em Pedir ajuste ou abono."
      toolbar={
        <button className="primary" onClick={() => router.select({ screen: "my-timesheet" })}>
          Abrir meu espelho
        </button>
      }
    >
      <ErrorText message={error} />
      <Group>
        {list.loading && !list.data ? (
          <Loading />
        ) : list.data?.length ? (
          list.data.map((r: AttendanceRequest) => {
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
          <Empty title="Você não tem pedidos" />
        )}
      </Group>
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
      title="Períodos fechados"
      subtitle="Confira o espelho de cada período e registre que tomou ciência."
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
                    ? "Reaberto pela empresa"
                    : undefined
              }
              accessory={
                <span className="toolbar">
                  <Download href={downloads.myTimesheet(companyId, c.start, c.end)}>
                    Espelho
                  </Download>
                  {!c.acknowledged_at && c.status === "closed" && (
                    <button onClick={() => setAcking(c.id)}>Dar ciência</button>
                  )}
                </span>
              }
            />
          ))
        ) : (
          <Empty title="Nenhum período fechado ainda" />
        )}
      </Group>
      <Sheet title="Dar ciência do espelho" open={acking !== null} onClose={() => setAcking(null)}>
        <p>Ao confirmar, fica registrado que você conferiu o espelho deste período fechado.</p>
        <Field label="Comentário (opcional)">
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
            Confirmar ciência
          </button>
        </div>
      </Sheet>
    </Screen>
  );
}
