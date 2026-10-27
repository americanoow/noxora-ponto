import { useState } from "react";
import {
  createHoliday,
  createRules,
  deleteHoliday,
  getRules,
  listHolidays,
} from "../api/attendance";
import {
  changePlan,
  confirmMfa,
  createPayrollProfile,
  disableMfa,
  downloads,
  getBilling,
  getPayrollProfiles,
  listGeneratedFiles,
  setCancel,
  startMfa,
} from "../api/operational";
import { getIdentificationMode, setIdentificationPolicy } from "../biometricsApi";
import { dateBR, dateTimeBR, isoDate, money, monthRange } from "../lib/format";
import { useObservable } from "../lib/observable";
import { useCompany, useSession } from "../lib/session";
import { useAction, useTask } from "../lib/task";
import { listUnits } from "../operationsApi";
import { EmployerTab } from "../TimeclockTab";
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
import { PeriodPicker } from "./Timesheet";

// ---------- Regras e feriados ----------

const PARAM_LABELS: Record<string, string> = {
  tolerance_per_mark_minutes: "Tolerância por marcação (min)",
  tolerance_daily_minutes: "Tolerância diária (min)",
  overtime_rate_percent: "Adicional de hora extra (%)",
  rest_day_overtime_rate_percent: "Adicional em folga/feriado (%)",
  night_start: "Início do horário noturno",
  night_end: "Fim do horário noturno",
  night_additional_percent: "Adicional noturno (%)",
  night_reduced_hour: "Hora noturna reduzida (52 min 30 s)",
  night_extension: "Prorrogação do horário noturno",
  break_rules: "Intervalos mínimos",
  min_rest_between_journeys_hours: "Descanso entre jornadas (h)",
  max_daily_overtime_minutes: "Alerta de extras por dia (min)",
  journey_split_gap_hours: "Separação de jornadas (h sem marcação)",
  duplicate_mark_window_seconds: "Janela de toque duplo (s)",
};

export function RulesScreen() {
  const { companyId } = useCompany();
  const rules = useTask(() => getRules(companyId), [companyId]);
  const year = new Date().getFullYear();
  const holidays = useTask(() => listHolidays(companyId, year), [companyId, year]);
  const units = useTask(() => listUnits(companyId), [companyId]);
  const [editing, setEditing] = useState(false);
  const [holiday, setHoliday] = useState({ date: "", name: "", unit: "" });
  const { pending, error, run } = useAction();

  const current = rules.data?.versions[0];
  const params = current?.params ?? rules.data?.defaults ?? {};

  return (
    <Screen
      title="Regras e feriados"
      subtitle={rules.data?.notice}
      toolbar={
        <button className="primary" onClick={() => setEditing(true)}>
          Nova versão das regras
        </button>
      }
    >
      {rules.loading && !rules.data ? (
        <Loading />
      ) : (
        <>
          <ErrorText message={rules.error} />
          <Group
            title={
              current
                ? `Versão ${current.version}, vigente desde ${dateBR(current.valid_from)}`
                : "Padrão do sistema (versão 0)"
            }
            footer="Mudanças criam uma nova versão com data de início. Dias anteriores continuam calculados pela versão da época."
          >
            {Object.entries(PARAM_LABELS).map(([key, label]) => (
              <Row
                key={key}
                title={label}
                subtitle={rules.data?.references[key]}
                value={formatParam(params[key])}
              />
            ))}
          </Group>
          {rules.data && rules.data.versions.length > 1 && (
            <Group title="Histórico de versões">
              {rules.data.versions.map((v) => (
                <Row
                  key={v.id}
                  title={`Versão ${v.version}`}
                  subtitle={v.note}
                  value={`desde ${dateBR(v.valid_from)}`}
                />
              ))}
            </Group>
          )}
        </>
      )}

      <Group
        title={`Feriados de ${year}`}
        footer="Cadastre os feriados nacionais, estaduais e municipais que valem para a empresa ou para uma unidade."
      >
        {holidays.data?.length ? (
          holidays.data.map((h) => (
            <Row
              key={h.id}
              title={h.name}
              subtitle={
                h.unit_id ? units.data?.find((u) => u.id === h.unit_id)?.name : "Todas as unidades"
              }
              value={dateBR(h.date)}
              accessory={
                <button
                  className="plain"
                  onClick={() =>
                    void run(async () => {
                      await deleteHoliday(companyId, h.id);
                      holidays.reload();
                    })
                  }
                >
                  Remover
                </button>
              }
            />
          ))
        ) : (
          <Empty title="Nenhum feriado cadastrado" />
        )}
        <form
          className="row"
          onSubmit={(e) => {
            e.preventDefault();
            void run(async () => {
              await createHoliday(
                companyId,
                holiday.date,
                holiday.name,
                holiday.unit ? Number(holiday.unit) : null,
              );
              setHoliday({ date: "", name: "", unit: "" });
              holidays.reload();
            });
          }}
        >
          <input
            type="date"
            aria-label="Data do feriado"
            value={holiday.date}
            onChange={(e) => setHoliday({ ...holiday, date: e.target.value })}
            required
          />
          <input
            aria-label="Nome do feriado"
            placeholder="Nome"
            value={holiday.name}
            onChange={(e) => setHoliday({ ...holiday, name: e.target.value })}
            required
          />
          <select
            aria-label="Unidade do feriado"
            value={holiday.unit}
            onChange={(e) => setHoliday({ ...holiday, unit: e.target.value })}
          >
            <option value="">Todas as unidades</option>
            {units.data?.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </select>
          <button type="submit" disabled={pending}>
            Adicionar feriado
          </button>
        </form>
      </Group>
      <ErrorText message={error} />
      {rules.data && (
        <RulesSheet
          open={editing}
          base={params}
          onClose={() => setEditing(false)}
          onDone={() => {
            setEditing(false);
            rules.reload();
          }}
        />
      )}
    </Screen>
  );
}

function formatParam(value: unknown): string {
  if (typeof value === "boolean") return value ? "Sim" : "Não";
  if (Array.isArray(value))
    return value
      .map(
        (r: { worked_over_minutes: number; min_break_minutes: number }) =>
          `${r.min_break_minutes} min acima de ${r.worked_over_minutes / 60} h`,
      )
      .join("; ");
  return String(value ?? "—");
}

function RulesSheet({
  open,
  base,
  onClose,
  onDone,
}: {
  open: boolean;
  base: Record<string, unknown>;
  onClose: () => void;
  onDone: () => void;
}) {
  const { companyId } = useCompany();
  const [values, setValues] = useState<Record<string, unknown>>(base);
  const [validFrom, setValidFrom] = useState(monthRange(isoDate(new Date())).from);
  const [note, setNote] = useState("");
  const { pending, error, run } = useAction();
  const set = (k: string, v: unknown) => setValues({ ...values, [k]: v });
  return (
    <Sheet title="Nova versão das regras" open={open} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            await createRules(companyId, validFrom, values, note);
            onDone();
          });
        }}
      >
        <div className="form-grid">
          <Field label="Vigente a partir de">
            <input
              type="date"
              value={validFrom}
              onChange={(e) => setValidFrom(e.target.value)}
              required
            />
          </Field>
          {Object.entries(PARAM_LABELS)
            .filter(([k]) => k !== "break_rules")
            .map(([k, label]) => {
              const v = values[k];
              return (
                <Field key={k} label={label}>
                  {typeof v === "boolean" ? (
                    <select value={v ? "1" : "0"} onChange={(e) => set(k, e.target.value === "1")}>
                      <option value="1">Sim</option>
                      <option value="0">Não</option>
                    </select>
                  ) : typeof v === "number" ? (
                    <input
                      type="number"
                      value={v}
                      onChange={(e) => set(k, Number(e.target.value))}
                    />
                  ) : (
                    <input type="time" value={String(v)} onChange={(e) => set(k, e.target.value)} />
                  )}
                </Field>
              );
            })}
        </div>
        <Field label="Motivo da mudança (ex.: nova convenção coletiva)">
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} />
        </Field>
        <ErrorText message={error} />
        <div className="actions">
          <button type="submit" disabled={pending}>
            Criar versão
          </button>
        </div>
      </form>
    </Sheet>
  );
}

// ---------- Relatórios e arquivos ----------

export function ReportsScreen() {
  const { companyId, isAdmin } = useCompany();
  const month = monthRange(isoDate(new Date()));
  const [period, setPeriod] = useState(month);
  const units = useTask(() => listUnits(companyId), [companyId]);
  const files = useTask(
    async () => (isAdmin ? listGeneratedFiles(companyId) : []),
    [companyId, isAdmin],
  );
  const profiles = useTask(
    async () => (isAdmin ? getPayrollProfiles(companyId) : null),
    [companyId, isAdmin],
  );
  const [creatingProfile, setCreatingProfile] = useState(false);

  return (
    <Screen
      title="Relatórios e arquivos"
      subtitle="Toda exportação fica registrada na auditoria."
      toolbar={
        <PeriodPicker
          from={period.from}
          to={period.to}
          onChange={(from, to) => setPeriod({ from, to })}
        />
      }
    >
      <Group title="Relatórios do período">
        <Row
          title="Resumo por funcionário"
          subtitle="Previsto, trabalhado, extras por adicional, débitos, noturno e faltas (CSV)"
          accessory={
            <Download href={downloads.summary(companyId, period.from, period.to)}>CSV</Download>
          }
        />
        <Row
          title="Marcações originais"
          subtitle="Registro de ponto com NSR e hash; CPF completo só para administradores (CSV)"
          accessory={
            <Download href={downloads.records(companyId, period.from, period.to)}>CSV</Download>
          }
        />
      </Group>
      {isAdmin && (
        <>
          <Group
            title="Arquivo Fonte de Dados (AFD)"
            footer="Gerado por unidade (estabelecimento). Sem assinatura ICP-Brasil; cabeçalho e trailer ainda precisam de conferência com o leiaute oficial."
          >
            {units.data?.map((u) => (
              <Row
                key={u.id}
                title={u.name}
                accessory={
                  <Download href={downloads.afd(companyId, u.id, period.from, period.to)}>
                    AFD
                  </Download>
                }
              />
            ))}
          </Group>
          <Group
            title="Perfis de exportação para a folha"
            aside={
              <button className="plain" onClick={() => setCreatingProfile(true)}>
                Novo perfil
              </button>
            }
            footer="A exportação para a folha usa sempre um período fechado. Baixe na tela do fechamento."
          >
            {profiles.data?.profiles.length ? (
              profiles.data.profiles.map((p) => (
                <Row
                  key={p.id}
                  title={p.name}
                  subtitle={Object.entries(p.event_codes)
                    .map(([event, code]) => `${profiles.data!.events[event]}: ${code}`)
                    .join("; ")}
                  value={p.file_format === "csv" ? "CSV" : "TXT"}
                />
              ))
            ) : (
              <Empty title="Nenhum perfil de folha">
                <p>
                  Associe os eventos da apuração aos códigos de rubrica do seu sistema de folha.
                </p>
              </Empty>
            )}
          </Group>
          <Group title="Arquivos gerados">
            {files.data?.length ? (
              <table>
                <thead>
                  <tr>
                    <th>Tipo</th>
                    <th>Período</th>
                    <th>Gerado</th>
                    <th>SHA-256</th>
                    <th>Pendências</th>
                  </tr>
                </thead>
                <tbody>
                  {files.data.map((f) => (
                    <tr key={f.id}>
                      <td>{f.kind === "afd" ? "AFD" : "Folha"}</td>
                      <td>
                        {dateBR(f.start)} a {dateBR(f.end)}
                      </td>
                      <td>
                        {dateTimeBR(f.generated_at)}
                        <br />
                        <small>{f.generated_by}</small>
                      </td>
                      <td>
                        <code style={{ fontSize: 11 }}>{f.sha256.slice(0, 16)}…</code>
                      </td>
                      <td>
                        {f.metadata.pending?.length ? (
                          <Badge tone="amber">{f.metadata.pending.length}</Badge>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty title="Nenhum arquivo gerado ainda" />
            )}
          </Group>
          {profiles.data && (
            <ProfileSheet
              open={creatingProfile}
              events={profiles.data.events}
              onClose={() => setCreatingProfile(false)}
              onDone={() => {
                setCreatingProfile(false);
                profiles.reload();
              }}
            />
          )}
        </>
      )}
    </Screen>
  );
}

function ProfileSheet({
  open,
  events,
  onClose,
  onDone,
}: {
  open: boolean;
  events: Record<string, string>;
  onClose: () => void;
  onDone: () => void;
}) {
  const { companyId } = useCompany();
  const [name, setName] = useState("");
  const [format, setFormat] = useState<"csv" | "fixed">("csv");
  const [codes, setCodes] = useState<Record<string, string>>({});
  const { pending, error, run } = useAction();
  return (
    <Sheet title="Perfil de folha" open={open} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            const filled = Object.fromEntries(Object.entries(codes).filter(([, v]) => v.trim()));
            await createPayrollProfile(companyId, name, format, filled);
            onDone();
          });
        }}
      >
        <div className="form-grid">
          <Field label="Nome">
            <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={80} />
          </Field>
          <Field label="Formato">
            <select value={format} onChange={(e) => setFormat(e.target.value as "csv" | "fixed")}>
              <option value="csv">CSV</option>
              <option value="fixed">TXT de largura fixa</option>
            </select>
          </Field>
          {Object.entries(events).map(([k, label]) => (
            <Field key={k} label={`Código: ${label}`}>
              <input
                value={codes[k] ?? ""}
                onChange={(e) => setCodes({ ...codes, [k]: e.target.value })}
                maxLength={6}
              />
            </Field>
          ))}
        </div>
        <ErrorText message={error} />
        <div className="actions">
          <button type="submit" disabled={pending}>
            Salvar perfil
          </button>
        </div>
      </form>
    </Sheet>
  );
}

// ---------- Empresa e identificação ----------

interface Policy {
  mode: "registration" | "face";
  offline_policy: "disabled" | "registration_only";
  face_liveness_policy: "certified" | "basic_challenge";
  engine: { name: string; version: string; simulator: boolean; liveness_method: string } | null;
}

export function CompanyScreen() {
  const { companyId } = useCompany();
  const policy = useTask(
    () => getIdentificationMode(companyId) as unknown as Promise<Policy>,
    [companyId],
  );
  const { error, run } = useAction();
  const change = (changes: Partial<Policy>) =>
    run(async () => {
      await setIdentificationPolicy(companyId, changes as never);
      policy.reload();
    });
  const p = policy.data;
  return (
    <Screen title="Empresa e identificação">
      <Group
        title="Identificação no tablet"
        padded
        footer={
          p?.engine
            ? `Motor: ${p.engine.name} ${p.engine.version}${p.engine.simulator ? " (simulador, só desenvolvimento)" : ""}.`
            : "Nenhum motor facial configurado no servidor."
        }
      >
        {!p ? (
          <Loading />
        ) : (
          <div className="form-grid">
            <Field label="Como o trabalhador se identifica">
              <select
                value={p.mode}
                onChange={(e) => void change({ mode: e.target.value as Policy["mode"] })}
              >
                <option value="registration">Somente matrícula (não é identificação forte)</option>
                <option value="face">Reconhecimento facial (ou código de exceção)</option>
              </select>
            </Field>
            <Field
              label="Prova de presença aceita"
              hint="O desafio básico (virar o rosto) barra foto parada, mas não é antifraude certificada."
            >
              <select
                value={p.face_liveness_policy}
                onChange={(e) =>
                  void change({
                    face_liveness_policy: e.target.value as Policy["face_liveness_policy"],
                  })
                }
              >
                <option value="certified">Somente vivacidade certificada</option>
                <option value="basic_challenge">Aceitar desafio básico de movimento</option>
              </select>
            </Field>
            <Field
              label="Tablet sem conexão"
              hint="Offline só por matrícula, sinalizado para revisão; o comprovante sai após a sincronização."
            >
              <select
                value={p.offline_policy}
                onChange={(e) =>
                  void change({ offline_policy: e.target.value as Policy["offline_policy"] })
                }
              >
                <option value="disabled">Não registrar sem conexão</option>
                <option value="registration_only">Registrar por matrícula e revisar</option>
              </select>
            </Field>
          </div>
        )}
        <ErrorText message={error ?? policy.error} />
      </Group>
      <Group title="Dados do empregador (comprovante e AFD)" padded>
        <div className="legacy">
          <EmployerTab companyId={companyId} canEdit />
        </div>
      </Group>
    </Screen>
  );
}

// ---------- Assinatura ----------

export function BillingScreen() {
  const { companyId } = useCompany();
  const billing = useTask(() => getBilling(companyId), [companyId]);
  const { pending, error, run } = useAction();
  const b = billing.data;
  const sub = b?.subscription;
  return (
    <Screen title="Assinatura" subtitle={b?.notice}>
      {!b ? (
        <Loading />
      ) : (
        <>
          <Group
            title="Situação"
            footer={sub?.sandbox ? "Ambiente de testes: nenhuma cobrança real é feita." : undefined}
          >
            <Row
              title="Plano"
              value={sub ? sub.plan.name : "Sem assinatura"}
              accessory={
                sub && (
                  <Badge
                    tone={sub.status === "active" || sub.status === "trialing" ? "tint" : "seal"}
                  >
                    {sub.status_label}
                  </Badge>
                )
              }
            />
            {sub?.trial_ends_at && <Row title="Teste até" value={dateBR(sub.trial_ends_at)} />}
            {sub && <Row title="Período atual até" value={dateBR(sub.current_period_end)} />}
            <Row
              title="Funcionários ativos"
              value={`${b.usage.active_employees}${sub?.plan.max_employees ? ` de ${sub.plan.max_employees}` : ""}`}
            />
            <Row
              title="Tablets"
              value={`${b.usage.active_devices}${sub?.plan.max_devices ? ` de ${sub.plan.max_devices}` : ""}`}
            />
            {sub && (
              <Row
                title={
                  sub.cancel_at_period_end
                    ? "Cancelamento agendado para o fim do período"
                    : "Renovação automática"
                }
                accessory={
                  <button
                    className={sub.cancel_at_period_end ? undefined : "destructive"}
                    disabled={pending}
                    onClick={() =>
                      void run(async () => {
                        await setCancel(companyId, !sub.cancel_at_period_end);
                        billing.reload();
                      })
                    }
                  >
                    {sub.cancel_at_period_end ? "Manter assinatura" : "Cancelar no fim do período"}
                  </button>
                }
              />
            )}
          </Group>
          <Group title="Planos">
            {b.plans.map((p) => (
              <Row
                key={p.code}
                title={p.name}
                subtitle={`${money(p.base_price_cents)} por mês + ${money(p.price_per_employee_cents)} por funcionário ativo. ${p.max_employees ? `Até ${p.max_employees} funcionários` : "Funcionários ilimitados"}, ${p.max_devices ? `${p.max_devices} tablets` : "tablets ilimitados"}.`}
                accessory={
                  sub?.plan.code === p.code ? (
                    <Badge tone="tint">Atual</Badge>
                  ) : (
                    <button
                      disabled={pending}
                      onClick={() =>
                        void run(async () => {
                          await changePlan(companyId, p.code);
                          billing.reload();
                        })
                      }
                    >
                      {sub ? "Mudar para este" : "Assinar"}
                    </button>
                  )
                }
              />
            ))}
          </Group>
          <ErrorText message={error} />
          <Group title="Faturas">
            {b.invoices.length ? (
              <table>
                <thead>
                  <tr>
                    <th>Período</th>
                    <th>Funcionários</th>
                    <th>Valor</th>
                    <th>Vencimento</th>
                    <th>Situação</th>
                  </tr>
                </thead>
                <tbody>
                  {b.invoices.map((i) => (
                    <tr key={i.id}>
                      <td>
                        {dateBR(i.period_start)} a {dateBR(i.period_end)}
                      </td>
                      <td className="num">{i.active_employees}</td>
                      <td className="num">{money(i.amount_cents)}</td>
                      <td>{dateBR(i.due_at)}</td>
                      <td>
                        <Badge
                          tone={
                            i.status === "paid" ? "tint" : i.status === "failed" ? "seal" : "amber"
                          }
                        >
                          {{ paid: "Paga", open: "Em aberto", failed: "Falhou", void: "Cancelada" }[
                            i.status
                          ] ?? i.status}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty title="Nenhuma fatura ainda" />
            )}
          </Group>
        </>
      )}
    </Screen>
  );
}

// ---------- Conta ----------

export function AccountScreen() {
  const session = useSession();
  const me = useObservable(session, (s) => s.me)!;
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const { pending, error, run } = useAction();
  return (
    <Screen title="Minha conta" subtitle={me.email}>
      <Group
        title="Verificação em duas etapas"
        padded
        footer="Use um aplicativo autenticador (Google Authenticator, Microsoft Authenticator, 1Password…). Recomendado para administradores."
      >
        {codes ? (
          <>
            <p>
              Guarde estes códigos de recuperação em local seguro. Cada um funciona uma vez e eles
              não serão mostrados de novo.
            </p>
            <pre style={{ background: "var(--fill)", padding: 12, borderRadius: 8 }}>
              {codes.join("\n")}
            </pre>
            <button
              onClick={() => {
                setCodes(null);
                void session.refresh();
              }}
            >
              Concluir
            </button>
          </>
        ) : me.mfa_enabled ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                await disableMfa(password, code);
                setCode("");
                setPassword("");
                await session.refresh();
              });
            }}
          >
            <p>
              <Badge tone="tint">Ativa</Badge>
            </p>
            <div className="form-grid">
              <Field label="Senha">
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </Field>
              <Field label="Código atual ou de recuperação">
                <input value={code} onChange={(e) => setCode(e.target.value)} required />
              </Field>
            </div>
            <div className="actions">
              <button type="submit" className="destructive" disabled={pending}>
                Desativar
              </button>
            </div>
          </form>
        ) : setup ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                setCodes((await confirmMfa(code)).recovery_codes);
                setSetup(null);
                setCode("");
              });
            }}
          >
            <p>
              No aplicativo autenticador, adicione uma conta pela chave abaixo (ou pelo endereço
              otpauth) e digite o código gerado.
            </p>
            <p>
              Chave:{" "}
              <code style={{ fontSize: 15, letterSpacing: 1 }}>
                {setup.secret.match(/.{1,4}/g)?.join(" ")}
              </code>
            </p>
            <p>
              <a href={setup.otpauth_uri}>Abrir no aplicativo autenticador</a>
            </p>
            <Field label="Código de 6 dígitos">
              <input
                inputMode="numeric"
                value={code}
                onChange={(e) => setCode(e.target.value.trim())}
                required
                maxLength={6}
              />
            </Field>
            <div className="actions">
              <button type="submit" disabled={pending}>
                Ativar
              </button>
            </div>
          </form>
        ) : (
          <button
            className="primary"
            disabled={pending}
            onClick={() => void run(async () => setSetup(await startMfa()))}
          >
            Configurar
          </button>
        )}
        <ErrorText message={error} />
      </Group>
      <Group title="Sessão">
        <Row
          title="Sair deste navegador"
          accessory={<button onClick={() => void session.signOut()}>Sair</button>}
        />
      </Group>
    </Screen>
  );
}
