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
    <Screen
      title="Meu ponto"
      subtitle="Suas batidas de ponto das últimas 48 horas e os comprovantes."
    >
      <Group
        title="Batidas recentes"
        footer="O comprovante é um PDF informativo. O comprovante oficial com assinatura digital ainda não está disponível."
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
              subtitle={`${r.unit.name}. Registro nº ${r.nsr}${r.offline ? ". Batida feita sem internet e enviada depois" : ""}`}
              accessory={
                <Download href={downloads.myReceipt(companyId, r.id)}>Comprovante</Download>
              }
            />
          ))
        ) : (
          <Empty title="Nenhuma batida nas últimas 48 horas" />
        )}
      </Group>
      <Group
        title="Como estou agora"
        padded
        footer="Serve para avisar a equipe. Isto não registra o seu ponto."
      >
        <p>
          Agora:{" "}
          {availability.data ? AVAILABILITY_LABELS[availability.data.status] : "nada informado"}
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
          title="Ver minha folha de ponto do mês"
          onClick={() => router.select({ screen: "my-timesheet" })}
        />
        <Row
          title="Pedir correção ou justificar ausência"
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
      title="Minha folha de ponto"
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
      subtitle="Para fazer um pedido, abra o dia na sua folha de ponto e toque em “Pedir correção ou justificar ausência”."
      toolbar={
        <button className="primary" onClick={() => router.select({ screen: "my-timesheet" })}>
          Abrir minha folha de ponto
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
          <Empty title="Você ainda não fez nenhum pedido" />
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
      title="Meses fechados"
      subtitle="Confira suas horas de cada período fechado e confirme que está tudo certo."
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
                  ? `Você confirmou em ${dateTimeBR(c.acknowledged_at)}`
                  : c.status === "reopened"
                    ? "A empresa reabriu este período"
                    : undefined
              }
              accessory={
                <span className="toolbar">
                  <Download href={downloads.myTimesheet(companyId, c.start, c.end)}>
                    Folha de ponto
                  </Download>
                  {!c.acknowledged_at && c.status === "closed" && (
                    <button onClick={() => setAcking(c.id)}>Está correto</button>
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
        <p>Ao confirmar, fica registrado que você conferiu suas horas deste período.</p>
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
            Confirmar que está correto
          </button>
        </div>
      </Sheet>
    </Screen>
  );
}
