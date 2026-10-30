import { useState } from "react";
import {
  type HourBank,
  type HourBankKind,
  addHourBankEntry,
  getHourBank,
  getMyHourBank,
  reverseHourBankEntry,
} from "../api/attendance";
import { dateBR, dateTimeBR, hm, isoDate } from "../lib/format";
import { useAction, useTask } from "../lib/task";
import { Badge, Empty, ErrorText, Field, Group, Loading, Row, Sheet, Stat, Stats } from "../ui/kit";

const KINDS: [Exclude<HourBankKind, "reversal">, string, string][] = [
  ["opening", "Saldo inicial", "Ponto de partida do banco de horas deste funcionário."],
  ["offset", "Folga compensada", "Horas abatidas do saldo por folga ou compensação."],
  ["payout", "Pagamento em dinheiro", "Horas quitadas na folha de pagamento."],
  ["adjustment", "Ajuste autorizado", "Correção autorizada, com motivo."],
];

const signed = (minutes: number) =>
  `${minutes < 0 ? "−" : minutes > 0 ? "+" : ""}${hm(Math.abs(minutes))}`;

/**
 * Banco de horas: livro-razão próprio, separado do "saldo do período" da folha de ponto. O saldo
 * soma lançamentos e o saldo dos períodos já fechados desde o saldo inicial. As regras de
 * compensação e prazo dependem de acordo ou convenção coletiva e precisam de conferência.
 */
export function HourBankSection({
  companyId,
  employeeId,
  canEdit,
  mine = false,
}: {
  companyId: number;
  employeeId?: number;
  canEdit: boolean;
  mine?: boolean;
}) {
  const bank = useTask(
    () => (mine ? getMyHourBank(companyId) : getHourBank(companyId, employeeId!)),
    [companyId, employeeId, mine],
  );
  const [adding, setAdding] = useState(false);
  const { pending, error, run } = useAction();
  const data = bank.data;

  return (
    <Group
      title="Banco de horas"
      aside={
        canEdit && data ? (
          <button className="plain" onClick={() => setAdding(true)}>
            Novo lançamento
          </button>
        ) : undefined
      }
      footer={data?.notice}
    >
      {bank.loading && !data ? (
        <Loading />
      ) : bank.error ? (
        <ErrorText message={bank.error} />
      ) : data ? (
        <>
          <Stats>
            <Stat
              label="Saldo do banco"
              figure={signed(data.balance_minutes)}
              tone={data.balance_minutes < 0 ? "seal" : "tint"}
            />
            <Stat label="Lançamentos" figure={signed(data.ledger_minutes)} />
            <Stat label="Períodos fechados" figure={signed(data.accrued_closed_minutes)} />
          </Stats>
          {data.opening_date ? (
            <p className="muted" style={{ margin: "8px 16px" }}>
              Contado a partir de {dateBR(data.opening_date)}.
            </p>
          ) : (
            <Empty title="Sem saldo inicial">
              <p>
                O banco de horas só passa a contar depois de um saldo inicial.
                {canEdit ? " Lance-o em “Novo lançamento”." : ""}
              </p>
            </Empty>
          )}
          <ErrorText message={error} />
          {data.entries.map((e) => (
            <Row
              key={e.id}
              title={`${e.kind_label}: ${signed(e.minutes)}`}
              subtitle={`${dateBR(e.date)} · ${e.reason} · ${e.created_by}, ${dateTimeBR(e.created_at)}`}
              accessory={
                <span className="toolbar">
                  {e.reversed && <Badge>Estornado</Badge>}
                  {canEdit && e.kind !== "reversal" && !e.reversed && (
                    <button
                      className="plain"
                      disabled={pending}
                      onClick={() => {
                        const reason = window.prompt("Motivo do estorno (mínimo de 5 letras):");
                        if (reason)
                          void run(async () => {
                            await reverseHourBankEntry(companyId, employeeId!, e.id, reason);
                            bank.reload();
                          });
                      }}
                    >
                      Estornar
                    </button>
                  )}
                </span>
              }
            />
          ))}
          {canEdit && (
            <EntrySheet
              open={adding}
              onClose={() => setAdding(false)}
              onSave={async (body) => {
                await addHourBankEntry(companyId, employeeId!, body);
                setAdding(false);
                bank.reload();
              }}
            />
          )}
        </>
      ) : null}
    </Group>
  );
}

function EntrySheet({
  open,
  onClose,
  onSave,
}: {
  open: boolean;
  onClose: () => void;
  onSave: (body: {
    kind: Exclude<HourBankKind, "reversal">;
    date: string;
    minutes: number;
    reason: string;
  }) => Promise<void>;
}) {
  const [kind, setKind] = useState<Exclude<HourBankKind, "reversal">>("opening");
  const [date, setDate] = useState(isoDate(new Date()));
  const [hours, setHours] = useState("");
  const [minutes, setMinutes] = useState("");
  const [reduce, setReduce] = useState(false);
  const [reason, setReason] = useState("");
  const { pending, error, run } = useAction();
  const alwaysReduces = kind === "offset" || kind === "payout";
  const total = (Number(hours) || 0) * 60 + (Number(minutes) || 0);

  return (
    <Sheet title="Novo lançamento no banco de horas" open={open} onClose={onClose}>
      <form
        style={{ display: "grid", gap: 12 }}
        onSubmit={(e) => {
          e.preventDefault();
          void run(() =>
            onSave({
              kind,
              date,
              minutes: alwaysReduces || reduce ? -total : total,
              reason,
            }),
          );
        }}
      >
        <Field label="Tipo" hint={KINDS.find(([k]) => k === kind)?.[2]}>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as Exclude<HourBankKind, "reversal">)}
          >
            {KINDS.map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <div className="form-grid">
          <Field label="Data">
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          </Field>
          <Field label="Horas">
            <input type="number" min={0} value={hours} onChange={(e) => setHours(e.target.value)} />
          </Field>
          <Field label="Minutos">
            <input
              type="number"
              min={0}
              max={59}
              value={minutes}
              onChange={(e) => setMinutes(e.target.value)}
            />
          </Field>
        </div>
        {!alwaysReduces && (
          <label style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <input type="checkbox" checked={reduce} onChange={(e) => setReduce(e.target.checked)} />
            Reduz o saldo (em vez de somar)
          </label>
        )}
        <Field
          label="Motivo"
          hint="Fica registrado com seu nome. Para corrigir um erro, estorne o lançamento."
        >
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            minLength={5}
            maxLength={300}
            required
          />
        </Field>
        <ErrorText message={error} />
        <div className="actions">
          <button type="submit" className="primary" disabled={pending || total === 0}>
            Lançar
          </button>
        </div>
      </form>
    </Sheet>
  );
}

export type { HourBank };
