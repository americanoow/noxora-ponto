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
      title="Fechamentos"
      subtitle="O fechamento congela a apuração do período para folha e espelho."
      toolbar={
        isAdmin && (
          <button className="primary" onClick={() => setCreating(true)}>
            Fechar período
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
              subtitle={`${c.employees} funcionário(s), fechado por ${c.closed_by?.email ?? "—"} em ${dateTimeBR(c.closed_at)}`}
              accessory={
                <Badge tone={c.status === "closed" ? "tint" : "amber"}>
                  {c.status === "closed" ? "Fechado" : "Reaberto"}
                </Badge>
              }
              onClick={() => router.push({ screen: "closing", id: c.id })}
            />
          ))
        ) : (
          <Empty title="Nenhum período fechado">
            {isAdmin && <p>Feche o mês depois de decidir os pedidos pendentes.</p>}
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
    <Sheet title="Fechar período" open={open} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(async () => onDone((await closePeriod(companyId, start, end)).id));
        }}
      >
        <div className="form-grid">
          <Field label="Início">
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} required />
          </Field>
          <Field label="Fim">
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} required />
          </Field>
        </div>
        <p style={{ color: "var(--ink-2)", marginTop: 12 }}>
          Todos os funcionários ativos entram no fechamento. Pedidos pendentes no período impedem o
          fechamento. Marcações que chegarem depois são gravadas normalmente e o espelho passa a
          indicar a divergência.
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
                Folha: {p.name}
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
        aside={`ciência de ${ackCount} de ${c.snapshot.employees.length}`}
      >
        <table>
          <thead>
            <tr>
              <th>Funcionário</th>
              <th>Trabalhado</th>
              <th>Extras</th>
              <th>Débito</th>
              <th>Faltas</th>
              <th>Ciência</th>
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
                      <Badge>Aguardando</Badge>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Group>
      <Group
        title="Integridade"
        footer="O hash identifica o conteúdo congelado. Ele não muda depois do fechamento."
      >
        <Row
          title="SHA-256 do instantâneo"
          value={<code style={{ fontSize: 12, wordBreak: "break-all" }}>{c.snapshot_sha256}</code>}
        />
        <Row title="Motor de apuração" value={c.engine_version} />
      </Group>
      <Sheet title="Reabrir período" open={reopening} onClose={() => setReopening(false)}>
        <p>
          A reabertura fica registrada na auditoria e libera ajustes no período. O instantâneo atual
          é preservado.
        </p>
        <Field label="Motivo">
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
