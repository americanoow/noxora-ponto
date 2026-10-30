import { useEffect, useState } from "react";
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
import { Badge, Dot, Empty, ErrorText, Field, Group, Loading, Screen, Segmented } from "../ui/kit";

export const STATUS_LABEL: Record<RequestStatus, [string, "amber" | "tint" | "seal" | undefined]> =
  {
    pending: ["Aguardando", "amber"],
    approved: ["Aprovada", "tint"],
    rejected: ["Recusada", "seal"],
    cancelled: ["Cancelada", undefined],
  };

export function describeRequest(r: AttendanceRequest): string {
  if (r.type === "justification") {
    return `${r.kind_label} em ${dateBR(r.date)}${r.minutes ? ` (${r.minutes} min)` : " (dia todo)"}`;
  }
  if (r.kind === "include") return `Esqueceu de bater: incluir ${dateTimeBR(r.occurred_at)}`;
  return `Registro por engano: ignorar ${dateTimeBR(r.record_occurred_at)}`;
}

const keyOf = (r: AttendanceRequest) => `${r.type}-${r.id}`;

export function RequestsScreen({ onDecided }: { onDecided?: () => void }) {
  const { companyId } = useCompany();
  const [status, setStatus] = useState<RequestStatus | "">("pending");
  const list = useTask(() => listRequests(companyId, status || undefined), [companyId, status]);
  const [selected, setSelected] = useState<string | null>(null);
  const items = list.data ?? [];
  const current = items.find((r) => keyOf(r) === selected) ?? items[0] ?? null;

  // Ao trocar o filtro, volta para o primeiro item da nova lista.
  useEffect(() => setSelected(null), [status]);

  return (
    <Screen
      title="Solicitações"
      subtitle="Pedidos de ajuste de ponto e justificativas de ausência. O registro original nunca é apagado."
      toolbar={
        <Segmented
          label="Situação"
          value={status}
          onChange={setStatus}
          options={[
            ["pending", "Aguardando"],
            ["approved", "Aprovadas"],
            ["rejected", "Recusadas"],
            ["", "Todas"],
          ]}
        />
      }
    >
      {list.loading && !list.data ? (
        <Loading />
      ) : list.error ? (
        <ErrorText message={list.error} />
      ) : items.length === 0 ? (
        <Group>
          <Empty
            title={
              status === "pending"
                ? "Nenhuma solicitação aguardando resposta"
                : "Nenhuma solicitação"
            }
          />
        </Group>
      ) : (
        <div className="master-detail">
          <Group>
            <div role="listbox" aria-label="Solicitações">
              {items.map((r) => {
                const [label, tone] = STATUS_LABEL[r.status];
                const active = current && keyOf(current) === keyOf(r);
                return (
                  <button
                    key={keyOf(r)}
                    role="option"
                    aria-selected={!!active}
                    aria-current={active ? "true" : undefined}
                    className="req-item"
                    onClick={() => setSelected(keyOf(r))}
                  >
                    <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <Dot
                        state={
                          r.status === "pending"
                            ? "hollow-warn"
                            : r.status === "approved"
                              ? "on"
                              : undefined
                        }
                      />
                      <b>{r.employee.name}</b>
                      <span style={{ marginLeft: "auto" }}>
                        <Badge tone={tone}>{label}</Badge>
                      </span>
                    </span>
                    <span>{describeRequest(r)}</span>
                    <small>Pedido em {dateTimeBR(r.requested_at)}</small>
                  </button>
                );
              })}
            </div>
          </Group>
          {current && (
            <RequestDetail
              key={keyOf(current)}
              item={current}
              onDone={() => {
                list.reload();
                onDecided?.();
              }}
            />
          )}
        </div>
      )}
    </Screen>
  );
}

/** Original x solicitado, justificativa, histórico e decisão — no mesmo lugar. */
function RequestDetail({ item, onDone }: { item: AttendanceRequest; onDone: () => void }) {
  const { companyId } = useCompany();
  const router = useRouter();
  const [note, setNote] = useState("");
  const { pending, error, run } = useAction();
  const [label, tone] = STATUS_LABEL[item.status];
  const decide = (approve: boolean) =>
    run(async () => {
      await decideRequest(companyId, item, approve, note);
      setNote("");
      onDone();
    });

  let before = "";
  let after = "";
  if (item.type === "justification") {
    before = `Dia ${dateBR(item.date)} sem justificativa`;
    after = `${item.kind_label}${item.minutes ? `, ${item.minutes} min` : ", dia todo"}`;
  } else if (item.kind === "include") {
    before = "Nenhum registro neste horário";
    after = `Incluir ${dateTimeBR(item.occurred_at)}`;
  } else {
    before = `Registro de ${dateTimeBR(item.record_occurred_at)}`;
    after = "Desconsiderar este registro (ele continua guardado)";
  }

  return (
    <div>
      <Group
        title={item.employee.name}
        aside={<Badge tone={tone}>{label}</Badge>}
        footer={`Matrícula ${item.employee.registration}`}
      >
        <div className="group-body padded" style={{ border: 0, boxShadow: "none" }}>
          <div className="panel-section">
            <h3>Original e solicitado</h3>
            <div className="compare">
              <div>
                <small>Original</small>
                <div className="big" style={{ fontSize: "var(--text-md)" }}>
                  {before}
                </div>
              </div>
              <div className="after">
                <small>Solicitado</small>
                <div className="big" style={{ fontSize: "var(--text-md)" }}>
                  {after}
                </div>
              </div>
            </div>
          </div>
          <div className="panel-section">
            <h3>Justificativa de quem pediu</h3>
            <p>{item.reason}</p>
          </div>
          {item.type === "justification" && item.document_ref && (
            <div className="panel-section">
              <h3>Documento de apoio</h3>
              <p>{item.document_ref}</p>
              <small style={{ color: "var(--ink-2)" }}>
                Visível só para quem pode decidir esta solicitação.
              </small>
            </div>
          )}
          <div className="panel-section">
            <h3>Histórico</h3>
            <ul className="history">
              <li>
                <Dot state="on" />
                <span>
                  Solicitada por {item.requested_by?.email ?? "—"}
                  <small>{dateTimeBR(item.requested_at)}</small>
                </span>
              </li>
              {item.decided_at && (
                <li>
                  <Dot state={item.status === "approved" ? "on" : "bad"} />
                  <span>
                    {label} por {item.decided_by?.email ?? "—"}
                    <small>
                      {dateTimeBR(item.decided_at)}
                      {item.decision_note ? ` · ${item.decision_note}` : ""}
                    </small>
                  </span>
                </li>
              )}
            </ul>
          </div>
          <div className="toolbar">
            <button
              onClick={() => router.push({ screen: "timesheet", employeeId: item.employee.id })}
            >
              Abrir folha de ponto
            </button>
          </div>
        </div>
      </Group>

      {item.status === "pending" && (
        <Group title="Sua decisão" padded>
          <Field label="Recado para quem pediu (obrigatório se for recusar)">
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
        </Group>
      )}
    </div>
  );
}
