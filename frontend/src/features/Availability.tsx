import { useState } from "react";
import {
  AVAILABILITY_LABELS,
  type AvailabilityStatus,
  type BoardEmployee,
  getBoard,
  setAvailability,
} from "../api/operational";
import { dateTimeBR } from "../lib/format";
import { useCompany } from "../lib/session";
import { useAction, useTask } from "../lib/task";
import { Badge, Empty, ErrorText, Field, Group, Loading, Row, Screen, Sheet } from "../ui/kit";

const TONE: Record<string, "tint" | "amber" | "seal" | undefined> = {
  available: "tint",
  busy: "amber",
  on_break: "amber",
  away: "amber",
  external: "amber",
  unavailable: "seal",
  unknown: undefined,
};

export function AvailabilityScreen() {
  const { companyId } = useCompany();
  const board = useTask(() => getBoard(companyId), [companyId]);
  const [editing, setEditing] = useState<BoardEmployee | null>(null);
  return (
    <Screen
      title="Disponibilidade"
      subtitle="Informação operacional por unidade e setor. Não altera nem substitui o registro de ponto."
      toolbar={<button onClick={board.reload}>Atualizar</button>}
    >
      {board.loading && !board.data ? (
        <Loading />
      ) : board.error ? (
        <ErrorText message={board.error} />
      ) : board.data && board.data.groups.length ? (
        board.data.groups.map((g) => (
          <Group
            key={`${g.unit?.id}-${g.sector?.id}`}
            title={`${g.unit?.name ?? "Sem unidade"}${g.sector ? `, ${g.sector.name}` : ""}`}
            aside={g.stale ? `${g.stale} desatualizado(s)` : undefined}
          >
            {g.employees.map((e) => (
              <Row
                key={e.employee.id}
                title={e.employee.name}
                subtitle={
                  [
                    e.note,
                    e.updated_at ? `atualizado ${dateTimeBR(e.updated_at)}` : "",
                    e.punch_hint?.text ?? "",
                  ]
                    .filter(Boolean)
                    .join(". ") || undefined
                }
                accessory={
                  <span className="toolbar">
                    {e.freshness === "stale" && <Badge>Desatualizado</Badge>}
                    {e.freshness === "expired" && <Badge>Vencido</Badge>}
                    <Badge tone={TONE[e.status]}>{AVAILABILITY_LABELS[e.status]}</Badge>
                  </span>
                }
                onClick={() => setEditing(e)}
              />
            ))}
          </Group>
        ))
      ) : (
        <Group>
          <Empty title="Nenhum funcionário lotado no seu escopo" />
        </Group>
      )}
      <StatusSheet
        employee={editing}
        onClose={() => setEditing(null)}
        onDone={() => {
          setEditing(null);
          board.reload();
        }}
      />
    </Screen>
  );
}

export function StatusPicker({
  value,
  onChange,
}: {
  value: AvailabilityStatus;
  onChange: (s: AvailabilityStatus) => void;
}) {
  return (
    <div className="toolbar" role="radiogroup" aria-label="Situação">
      {(Object.keys(AVAILABILITY_LABELS) as (AvailabilityStatus | "unknown")[])
        .filter((k): k is AvailabilityStatus => k !== "unknown")
        .map((k) => (
          <button
            key={k}
            type="button"
            role="radio"
            aria-checked={value === k}
            aria-pressed={value === k}
            onClick={() => onChange(k)}
          >
            {AVAILABILITY_LABELS[k]}
          </button>
        ))}
    </div>
  );
}

function StatusSheet({
  employee,
  onClose,
  onDone,
}: {
  employee: BoardEmployee | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const { companyId } = useCompany();
  const [status, setStatus] = useState<AvailabilityStatus>("available");
  const [note, setNote] = useState("");
  const [expires, setExpires] = useState("");
  const { pending, error, run } = useAction();
  if (!employee) return null;
  return (
    <Sheet title={employee.employee.name} open={!!employee} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            await setAvailability(
              companyId,
              employee.employee.id,
              status,
              note,
              expires ? Number(expires) : undefined,
            );
            setNote("");
            onDone();
          });
        }}
        style={{ display: "grid", gap: 12 }}
      >
        <StatusPicker value={status} onChange={setStatus} />
        <div className="form-grid">
          <Field label="Observação">
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={140} />
          </Field>
          <Field label="Vence em (minutos)">
            <input
              type="number"
              min={1}
              max={1440}
              value={expires}
              onChange={(e) => setExpires(e.target.value)}
            />
          </Field>
        </div>
        <ErrorText message={error} />
        <div className="actions">
          <button type="submit" disabled={pending}>
            Salvar situação
          </button>
        </div>
      </form>
    </Sheet>
  );
}
