import { useState } from "react";
import {
  closePeriod,
  getClosing,
  listAcknowledgements,
  listClosings,
  reopenPeriod,
} from "../api/attendance";
import { downloads, getPayrollProfiles } from "../api/operational";
import { addDays, dateBR, dateTimeBR, hm, isoDate, monthRange } from "../lib/format";
import { useRouter } from "../lib/router";
import { useCompany } from "../lib/session";
import { useAction, useTask } from "../lib/task";
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

export function ClosingsScreen() {
  const { companyId, isAdmin } = useCompany();
  const router = useRouter();
  const list = useTask(() => listClosings(companyId), [companyId]);
  const [creating, setCreating] = useState(false);
  return (
    <Screen
      title="Fechar o mês"
      subtitle="Ao fechar, as horas do período ficam travadas para a folha de pagamento e para a conferência dos funcionários."
      toolbar={
        isAdmin && (
          <button className="primary" onClick={() => setCreating(true)}>
            Fechar um período
          </button>
        )
      }
    >
      <Group>
        {list.loading && !list.data ? (
          <Loading />
        ) : list.error ? (
          <ErrorText message={list.error} />
        ) : list.data && list.data.length ? (
          list.data.map((c) => (
            <Row
              key={c.id}
              title={`${dateBR(c.start)} a ${dateBR(c.end)}`}
              subtitle={`${c.employees} funcionário(s). Fechado por ${c.closed_by?.email ?? "—"} em ${dateTimeBR(c.closed_at)}`}
              accessory={
                <Badge tone={c.status === "closed" ? "tint" : "amber"}>
                  {c.status === "closed" ? "Fechado" : "Reaberto"}
                </Badge>
              }
              onClick={() => router.push({ screen: "closing", id: c.id })}
            />
          ))
        ) : (
          <Empty title="Nenhum período fechado ainda">
            {isAdmin && <p>Feche o mês depois de responder a todos os pedidos aguardando.</p>}
          </Empty>
        )}
      </Group>
      <CloseSheet
        open={creating}
        onClose={() => setCreating(false)}
        onDone={(id) => {
          setCreating(false);
          list.reload();
          router.push({ screen: "closing", id });
        }}
      />
    </Screen>
  );
}

function CloseSheet({
  open,
  onClose,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  onDone: (id: number) => void;
}) {
  const { companyId } = useCompany();
  const last = monthRange(addDays(monthRange(isoDate(new Date())).from, -1));
  const [start, setStart] = useState(last.from);
  const [end, setEnd] = useState(last.to);
  const { pending, error, run } = useAction();
  return (
    <Sheet title="Fechar um período" open={open} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(async () => onDone((await closePeriod(companyId, start, end)).id));
        }}
      >
        <div className="form-grid">
          <Field label="Primeiro dia">
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} required />
          </Field>
          <Field label="Último dia">
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} required />
          </Field>
        </div>
        <p style={{ color: "var(--ink-2)", marginTop: 12 }}>
          Todos os funcionários ativos entram no fechamento. Se houver pedidos aguardando resposta
          nesse período, não será possível fechar. Batidas que chegarem depois continuam sendo
          guardadas, e a folha de ponto avisará que mudou.
        </p>
        <ErrorText message={error} />
        <div className="actions">
          <button type="submit" disabled={pending}>
            Fechar período
          </button>
        </div>
      </form>
    </Sheet>
  );
}

export function ClosingDetailScreen({ id }: { id: number }) {
  const { companyId, isAdmin } = useCompany();
  const router = useRouter();
  const closing = useTask(() => getClosing(companyId, id), [companyId, id]);
  const acks = useTask(() => listAcknowledgements(companyId, id), [companyId, id]);
  const profiles = useTask(
    async () => (isAdmin ? (await getPayrollProfiles(companyId)).profiles : []),
    [companyId, isAdmin],
  );
  const [reopening, setReopening] = useState(false);
  const [reason, setReason] = useState("");
  const { pending, error, run } = useAction();
  const c = closing.data;
  if (closing.loading && !c)
    return (
      <Screen title="Fechamento">
        <Loading />
      </Screen>
    );
  if (!c)
    return (
      <Screen title="Fechamento">
        <ErrorText message={closing.error} />
      </Screen>
    );
  const ackCount = acks.data?.filter((a) => a.acknowledged_at).length ?? 0;

  return (
    <Screen
      title={`${dateBR(c.start)} a ${dateBR(c.end)}`}
      subtitle={
        c.status === "closed"
          ? "Fechado"
          : `Reaberto em ${dateTimeBR(c.reopened_at)}: ${c.reopen_reason}`
      }
      toolbar={
        <>
          {isAdmin &&
            c.status === "closed" &&
            profiles.data?.map((p) => (
              <Download key={p.id} href={downloads.payroll(companyId, p.id, c.id)}>
                Folha de pagamento: {p.name}
              </Download>
            ))}
          {isAdmin && c.status === "closed" && (
            <button className="destructive" onClick={() => setReopening(true)}>
              Reabrir
            </button>
          )}
        </>
      }
    >
      <Group
        title="Funcionários"
        aside={`${ackCount} de ${c.snapshot.employees.length} já conferiram`}
      >
        <table>
          <thead>
            <tr>
              <th>Funcionário</th>
              <th>Horas trabalhadas</th>
              <th>Horas extras</th>
              <th>Horas devidas</th>
              <th>Faltas</th>
              <th>Conferiu?</th>
            </tr>
          </thead>
          <tbody>
            {c.snapshot.employees.map((e) => {
              const ack = acks.data?.find((a) => a.employee.id === e.employee.id);
              return (
                <tr key={e.employee.id}>
                  <td>
                    <button
                      className="plain"
                      onClick={() =>
                        router.push({
                          screen: "timesheet",
                          employeeId: e.employee.id,
                          from: c.start,
                          to: c.end,
                        })
                      }
                    >
                      {e.employee.name}
                    </button>
                  </td>
                  <td className="num">{hm(e.totals.worked_minutes)}</td>
                  <td className="num">{hm(e.totals.overtime_minutes)}</td>
                  <td className="num">{hm(e.totals.deficit_minutes)}</td>
                  <td className="num">{e.totals.absences}</td>
                  <td>
                    {ack?.acknowledged_at ? (
                      <Badge tone={ack.matches_snapshot ? "tint" : "amber"}>
                        {dateTimeBR(ack.acknowledged_at)}
                      </Badge>
                    ) : (
                      <Badge>Ainda não</Badge>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Group>
      <Group
        title="Garantia de que nada mudou"
        footer="Este código é uma “impressão digital” do período fechado. Se qualquer número mudasse, o código mudaria."
      >
        <Row
          title="Código de verificação"
          value={<code style={{ fontSize: 12, wordBreak: "break-all" }}>{c.snapshot_sha256}</code>}
        />
        <Row title="Versão do cálculo" value={c.engine_version} />
      </Group>
      <Sheet title="Reabrir o período" open={reopening} onClose={() => setReopening(false)}>
        <p>
          A reabertura fica registrada no histórico e permite novas correções no período. A cópia do
          fechamento atual é guardada.
        </p>
        <Field label="Motivo da reabertura" hint="Escreva pelo menos 5 letras.">
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            minLength={5}
            required
          />
        </Field>
        <ErrorText message={error} />
        <div className="actions">
          <button
            className="destructive"
            disabled={pending}
            onClick={() =>
              void run(async () => {
                await reopenPeriod(companyId, c.id, reason);
                setReopening(false);
                closing.reload();
              })
            }
          >
            Reabrir período
          </button>
        </div>
      </Sheet>
    </Screen>
  );
}
