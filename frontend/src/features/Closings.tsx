import { useState } from "react";
import { ApiError } from "../http";
import {
  type SummaryRow,
  closePeriod,
  getClosing,
  getSummary,
  listAcknowledgements,
  listClosings,
  listRequests,
  reopenPeriod,
} from "../api/attendance";
import { downloads, getPayrollProfiles } from "../api/operational";
import { listDevices } from "../devicesApi";
import { addDays, dateBR, dateTimeBR, hm, isoDate, monthRange } from "../lib/format";
import { useRouter } from "../lib/router";
import { useCompany } from "../lib/session";
import { usePaged } from "../lib/paged";
import { useAction, useTask } from "../lib/task";
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

export function ClosingsScreen() {
  const { companyId, isAdmin } = useCompany();
  const router = useRouter();
  const list = usePaged((page) => listClosings(companyId, page), [companyId]);
  const [closing, setClosing] = useState(false);
  if (closing)
    return (
      <CloseWizard
        onCancel={() => setClosing(false)}
        onClosed={() => {
          list.reload();
        }}
      />
    );
  return (
    <Screen
      title="Fechamento"
      subtitle="Ao fechar, as horas do período ficam registradas para a folha de pagamento e para a conferência dos funcionários."
      toolbar={
        isAdmin && (
          <button className="primary" onClick={() => setClosing(true)}>
            Fechar o mês
          </button>
        )
      }
    >
      <Group>
        {list.loading && !list.ready ? (
          <Loading />
        ) : list.error && !list.items.length ? (
          <ErrorText message={list.error} />
        ) : list.items.length ? (
          list.items.map((c) => (
            <Row
              key={c.id}
              title={`${dateBR(c.start)} a ${dateBR(c.end)}`}
              subtitle={`${c.employees} funcionário(s). Fechado por ${c.closed_by?.email ?? "—"} em ${dateTimeBR(c.closed_at)}`}
              accessory={
                <span className="toolbar">
                  {c.exceptions && <Badge tone="amber">Com exceção</Badge>}
                  <Badge tone={c.status === "closed" ? "tint" : "amber"}>
                    {c.status === "closed" ? "Período fechado" : "Reabertura registrada"}
                  </Badge>
                </span>
              }
              onClick={() => router.push({ screen: "closing", id: c.id })}
            />
          ))
        ) : (
          <Empty title="Nenhum período fechado ainda">
            {isAdmin && <p>Feche o mês depois de responder a todas as solicitações aguardando.</p>}
          </Empty>
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

const STEPS = ["Conferir", "Revisar totais", "Confirmar", "Documentos"];

function Stepper({ step }: { step: number }) {
  return (
    <ol className="stepper" aria-label="Etapas do fechamento">
      {STEPS.map((s, i) => (
        <li
          key={s}
          className={i < step ? "done" : undefined}
          aria-current={i === step ? "step" : undefined}
        >
          <span className="n">{i + 1}</span>
          {s}
        </li>
      ))}
    </ol>
  );
}

/** Fluxo guiado: conferir → revisar totais → confirmar → documentos. */
function CloseWizard({ onCancel, onClosed }: { onCancel: () => void; onClosed: () => void }) {
  const { companyId } = useCompany();
  const router = useRouter();
  const last = monthRange(addDays(monthRange(isoDate(new Date())).from, -1));
  const [step, setStep] = useState(0);
  const [start, setStart] = useState(last.from);
  const [end, setEnd] = useState(last.to);
  const [ok, setOk] = useState(false);
  // Excecao autorizada: so aparece depois que o servidor recusa por registro incompleto.
  const [needsException, setNeedsException] = useState(false);
  const [exceptionReason, setExceptionReason] = useState("");
  const [closedId, setClosedId] = useState<number | null>(null);
  const { pending, error, run } = useAction();

  // So os pendentes dentro do periodo barram o fechamento; o servidor filtra e informa o total real.
  const requests = useTask(
    () => listRequests(companyId, { status: "pending", from: start, to: end, pageSize: 1 }),
    [companyId, start, end],
  );
  const devices = useTask(() => listDevices(companyId), [companyId]);
  const summary = useTask(() => getSummary(companyId, start, end), [companyId, start, end]);
  const profiles = useTask(
    async () => (closedId ? (await getPayrollProfiles(companyId)).profiles : []),
    [companyId, closedId],
  );

  const blockingCount = requests.data?.count ?? 0;
  const rows: SummaryRow[] = summary.data?.results ?? [];
  const incomplete = rows.reduce((n, r) => n + r.totals.inconsistent_days, 0);
  const absences = rows.reduce((n, r) => n + r.totals.absences, 0);
  // O resumo e paginado: se ha mais paginas, as contagens abaixo cobrem so parte dos funcionarios.
  const partial = Boolean(summary.data?.next);
  const silent = (devices.data ?? []).filter(
    (d) => d.status === "active" && d.connectivity !== "online",
  );
  const loaded = !requests.loading && !summary.loading && !devices.loading;

  return (
    <Screen
      title="Fechar o mês"
      subtitle="Quatro etapas: conferir, revisar os totais, confirmar e acessar os documentos."
      toolbar={
        closedId === null && (
          <button className="plain" onClick={onCancel}>
            Cancelar
          </button>
        )
      }
    >
      <Stepper step={step} />

      {step === 0 && (
        <>
          <Group padded>
            <div className="form-grid">
              <Field label="Primeiro dia">
                <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
              </Field>
              <Field label="Último dia">
                <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
              </Field>
            </div>
          </Group>
          <Group
            title="O que conferir"
            footer="Pendências conhecidas e tablets sem comunicação são coisas diferentes: no segundo caso, o sistema não consegue saber se há registros ainda não enviados."
          >
            {!loaded ? (
              <Loading />
            ) : (
              <ul className="checks">
                <li>
                  <Dot state={blockingCount ? "warn" : "on"} />
                  <div>
                    <b>
                      {blockingCount
                        ? `${blockingCount} solicitação(ões) aguardando resposta no período`
                        : "Nenhuma solicitação aguardando no período"}
                    </b>
                    <small>
                      {blockingCount
                        ? "Responda antes de fechar: elas impedem o fechamento."
                        : "Tudo respondido."}
                    </small>
                  </div>
                  {blockingCount > 0 && (
                    <button onClick={() => router.select({ screen: "requests" })}>
                      Abrir solicitações
                    </button>
                  )}
                </li>
                <li>
                  <Dot state={incomplete ? "hollow-warn" : "on"} />
                  <div>
                    <b>
                      {incomplete
                        ? `${incomplete} dia(s) com registro incompleto`
                        : "Nenhum registro incompleto"}
                    </b>
                    <small>
                      {partial
                        ? "Contagem apenas das primeiras páginas do resumo; o fechamento confere todos. "
                        : ""}
                      Sem ajuste aprovado, o fechamento é recusado. Só um administrador pode
                      autorizar uma exceção, com motivo registrado.
                    </small>
                  </div>
                </li>
                <li>
                  <Dot state={absences ? "hollow-warn" : "on"} />
                  <div>
                    <b>{absences} falta(s) no período</b>
                    <small>Confira se há justificativas a registrar.</small>
                  </div>
                </li>
                <li>
                  <Dot state={silent.length ? "hollow-warn" : "on"} />
                  <div>
                    <b>
                      {silent.length
                        ? `${silent.length} tablet(s) sem comunicação recente`
                        : "Todos os tablets ativos estão se comunicando"}
                    </b>
                    <small>
                      {silent.length
                        ? `${silent.map((d) => d.name).join(", ")}. Não conseguimos confirmar se há registros guardados nesses tablets ainda sem envio.`
                        : "Mesmo assim, registros feitos sem internet só chegam quando o tablet reconecta."}
                    </small>
                  </div>
                </li>
              </ul>
            )}
          </Group>
          <div className="actions">
            <button
              className="primary"
              disabled={!loaded || blockingCount > 0 || !start || !end}
              onClick={() => setStep(1)}
            >
              Continuar
            </button>
          </div>
        </>
      )}

      {step === 1 && (
        <>
          <Group
            title={`Totais por funcionário · ${dateBR(start)} a ${dateBR(end)}`}
            aside={summary.data ? `${summary.data.count} funcionário(s)` : undefined}
          >
            {summary.loading ? (
              <Loading />
            ) : summary.error ? (
              <ErrorText message={summary.error} />
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Funcionário</th>
                    <th>Horas trabalhadas</th>
                    <th>Horas extras</th>
                    <th>Horas devidas</th>
                    <th>Faltas</th>
                    <th>Incompletos</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.employee.id}>
                      <td>{r.employee.name}</td>
                      <td className="num">{hm(r.totals.worked_minutes)}</td>
                      <td className="num">{hm(r.totals.overtime_minutes)}</td>
                      <td className="num">{hm(r.totals.deficit_minutes)}</td>
                      <td className="num">{r.totals.absences}</td>
                      <td className="num">{r.totals.inconsistent_days}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Group>
          <div className="actions">
            <button onClick={() => setStep(0)}>Voltar</button>
            <button className="primary" onClick={() => setStep(2)}>
              Continuar
            </button>
          </div>
        </>
      )}

      {step === 2 && (
        <Group title="Confirmar o fechamento" padded>
          <p>
            Período de <b>{dateBR(start)}</b> a <b>{dateBR(end)}</b>, com todos os funcionários
            ativos. Depois de fechar:
          </p>
          <ul className="steps">
            <li>o período fica registrado como fechado, com quem fechou e quando;</li>
            <li>
              registros que chegarem depois continuam guardados, e a folha de ponto mostrará que ela
              difere da versão fechada;
            </li>
            <li>a reabertura é possível e fica registrada com o motivo.</li>
          </ul>
          <label style={{ display: "flex", gap: 10, alignItems: "center", margin: "12px 0" }}>
            <input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} />
            Revisei as pendências e os totais deste período.
          </label>
          {needsException && (
            <Field
              label="Motivo da exceção"
              hint="Há dias com registro incompleto. Para fechar assim mesmo, explique o motivo (mínimo de 10 letras). Fica registrado com seu nome e aparece no fechamento."
            >
              <textarea
                rows={3}
                value={exceptionReason}
                onChange={(e) => setExceptionReason(e.target.value)}
              />
            </Field>
          )}
          <ErrorText message={error} />
          <div className="actions">
            <button onClick={() => setStep(1)}>Voltar</button>
            <button
              className="primary"
              disabled={!ok || pending || (needsException && exceptionReason.trim().length < 10)}
              onClick={() =>
                void run(async () => {
                  try {
                    const c = await closePeriod(
                      companyId,
                      start,
                      end,
                      needsException ? exceptionReason.trim() : undefined,
                    );
                    setClosedId(c.id);
                    setStep(3);
                    onClosed();
                  } catch (e) {
                    if (e instanceof ApiError && e.body.code === "incomplete_marks")
                      setNeedsException(true);
                    throw e;
                  }
                })
              }
            >
              {needsException ? "Fechar com exceção" : "Fechar período"}
            </button>
          </div>
        </Group>
      )}

      {step === 3 && closedId !== null && (
        <>
          <p className="notice info" role="status">
            <b>Período fechado.</b> {dateBR(start)} a {dateBR(end)}.
          </p>
          <Group title="Documentos e exportações">
            <Row
              title="Ver o fechamento"
              subtitle="Totais por funcionário, quem conferiu e o código de verificação."
              onClick={() => router.push({ screen: "closing", id: closedId })}
            />
            {profiles.data?.map((p) => (
              <Row
                key={p.id}
                title={`Arquivo da folha de pagamento: ${p.name}`}
                accessory={
                  <Download href={downloads.payroll(companyId, p.id, closedId)}>Baixar</Download>
                }
              />
            ))}
            <Row
              title="Relatórios e arquivos"
              subtitle="Planilhas do período e arquivo para a fiscalização (AFD)."
              onClick={() => router.select({ screen: "reports" })}
            />
          </Group>
          <div className="actions">
            <button className="primary" onClick={onCancel}>
              Concluir
            </button>
          </div>
        </>
      )}
    </Screen>
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
          ? "Período fechado"
          : `Reabertura registrada em ${dateTimeBR(c.reopened_at)}: ${c.reopen_reason}`
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
      {c.exceptions && (
        <div className="notice warn" role="status">
          <b>Fechado com exceção.</b> {c.exceptions.authorized_by.email} autorizou em{" "}
          {dateTimeBR(c.exceptions.authorized_at)}. Motivo: {c.exceptions.reason}. Dias incompletos:{" "}
          {c.exceptions.employees
            .map((e) => `${e.name} (${e.dates.map(dateBR).join(", ")})`)
            .join("; ")}
          .
        </div>
      )}
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
        title="Código de verificação"
        footer="O código identifica o conteúdo registrado neste fechamento e permite conferir se ele foi alterado depois. Ele não substitui a validação jurídica dos documentos."
      >
        <Row
          title="Código do conteúdo fechado"
          value={<code style={{ fontSize: 12, wordBreak: "break-all" }}>{c.snapshot_sha256}</code>}
        />
        <Row title="Versão do cálculo" value={c.engine_version} />
      </Group>
      <Sheet title="Reabrir o período" open={reopening} onClose={() => setReopening(false)}>
        <p>
          A reabertura fica registrada com o seu nome e o motivo, e permite novas correções no
          período. O conteúdo do fechamento atual é preservado.
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
            Registrar reabertura
          </button>
        </div>
      </Sheet>
    </Screen>
  );
}
