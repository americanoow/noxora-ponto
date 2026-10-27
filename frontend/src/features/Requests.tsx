import { useState } from "react";
import {
  type AttendanceRequest,
  type RequestStatus,
  decideRequest,
  listRequests,
} from "../api/attendance";
import { dateBR, dateTimeBR } from "../lib/format";
import { useRouter } from "../lib/router";
import { useCompany } from "../lib/session";
import { useAction, useTask } from "../lib/task";
import {
  Badge,
  Empty,
  ErrorText,
  Field,
  Group,
  Loading,
  Screen,
  Segmented,
  Sheet,
} from "../ui/kit";

export const STATUS_LABEL: Record<RequestStatus, [string, "amber" | "tint" | "seal" | undefined]> =
  {
    pending: ["Pendente", "amber"],
    approved: ["Aprovado", "tint"],
    rejected: ["Recusado", "seal"],
    cancelled: ["Cancelado", undefined],
  };

export function describeRequest(r: AttendanceRequest): string {
  if (r.type === "justification") {
    return `${r.kind_label} em ${dateBR(r.date)}${r.minutes ? ` (${r.minutes} min)` : " (dia todo)"}`;
  }
  if (r.kind === "include") return `Incluir marcação às ${dateTimeBR(r.occurred_at)}`;
  return `Desconsiderar marcação de ${dateTimeBR(r.record_occurred_at)}`;
}

export function RequestsScreen({ onDecided }: { onDecided?: () => void }) {
  const { companyId } = useCompany();
  const router = useRouter();
  const [status, setStatus] = useState<RequestStatus | "">("pending");
  const list = useTask(() => listRequests(companyId, status || undefined), [companyId, status]);
  const [selected, setSelected] = useState<AttendanceRequest | null>(null);

  return (
    <Screen
      title="Pedidos"
      subtitle="Inclusões, desconsiderações e abonos. A marcação original nunca é alterada."
      toolbar={
        <Segmented
          label="Situação"
          value={status}
          onChange={setStatus}
          options={[
            ["pending", "Pendentes"],
            ["approved", "Aprovados"],
            ["rejected", "Recusados"],
            ["", "Todos"],
          ]}
        />
      }
    >
      <Group>
        {list.loading && !list.data ? (
          <Loading />
        ) : list.error ? (
          <ErrorText message={list.error} />
        ) : list.data && list.data.length ? (
          <table>
            <thead>
              <tr>
                <th>Funcionário</th>
                <th>Pedido</th>
                <th>Justificativa</th>
                <th>Pedido por</th>
                <th>Situação</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data.map((r) => {
                const [label, tone] = STATUS_LABEL[r.status];
                return (
                  <tr key={`${r.type}-${r.id}`}>
                    <td>
                      <button
                        className="plain"
                        onClick={() =>
                          router.push({
                            screen: "timesheet",
                            employeeId: r.employee.id,
                          })
                        }
                      >
                        {r.employee.name}
                      </button>
                    </td>
                    <td>{describeRequest(r)}</td>
                    <td>{r.reason}</td>
                    <td>
                      {r.requested_by?.email}
                      <br />
                      <small style={{ color: "var(--ink-3)" }}>{dateTimeBR(r.requested_at)}</small>
                    </td>
                    <td>
                      <Badge tone={tone}>{label}</Badge>
                      {r.decision_note && (
                        <div style={{ fontSize: 12, color: "var(--ink-3)" }}>{r.decision_note}</div>
                      )}
                    </td>
                    <td>
                      {r.status === "pending" && (
                        <button onClick={() => setSelected(r)}>Decidir</button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <Empty title={status === "pending" ? "Nenhum pedido pendente" : "Nenhum pedido"} />
        )}
      </Group>
      <DecisionSheet
        item={selected}
        onClose={() => setSelected(null)}
        onDone={() => {
          setSelected(null);
          list.reload();
          onDecided?.();
        }}
      />
    </Screen>
  );
}

function DecisionSheet({
  item,
  onClose,
  onDone,
}: {
  item: AttendanceRequest | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const { companyId } = useCompany();
  const [note, setNote] = useState("");
  const { pending, error, run } = useAction();
  if (!item) return null;
  const decide = (approve: boolean) =>
    run(async () => {
      await decideRequest(companyId, item, approve, note);
      setNote("");
      onDone();
    });
  return (
    <Sheet title="Decidir pedido" open={!!item} onClose={onClose}>
      <p>
        <strong>{item.employee.name}</strong>
      </p>
      <p>{describeRequest(item)}</p>
      <p style={{ color: "var(--ink-2)" }}>Justificativa: {item.reason}</p>
      {item.type === "justification" && item.document_ref && <p>Documento: {item.document_ref}</p>}
      <Field label="Observação (obrigatória para recusar)">
        <textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
      </Field>
      <ErrorText message={error} />
      <div className="actions">
        <button className="destructive" disabled={pending} onClick={() => void decide(false)}>
          Recusar
        </button>
        <button className="primary" disabled={pending} onClick={() => void decide(true)}>
          Aprovar
        </button>
      </div>
    </Sheet>
  );
}
