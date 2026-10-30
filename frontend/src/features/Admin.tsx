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
  reauthenticate,
  createPayrollProfile,
  disableMfa,
  downloads,
  getBilling,
  getPayrollProfiles,
  setAvailabilityEnabled,
  listGeneratedFiles,
  setCancel,
  startMfa,
} from "../api/operational";
import { getIdentificationMode, setIdentificationPolicy } from "../biometricsApi";
import { dateBR, dateTimeBR, isoDate, money, monthRange } from "../lib/format";
import { useObservable } from "../lib/observable";
import { useCompany, useSession } from "../lib/session";
import { usePaged } from "../lib/paged";
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
  LoadMore,
  Loading,
  Row,
  Screen,
  Sheet,
} from "../ui/kit";
import { ApiError } from "../http";
import { useModules } from "../lib/modules";
import { PeriodPicker } from "./Timesheet";

// ---------- Regras e feriados ----------

const PARAM_LABELS: Record<string, string> = {
  tolerance_per_mark_minutes: "Tolerância em cada batida (minutos)",
  tolerance_daily_minutes: "Tolerância por dia (minutos)",
  overtime_rate_percent: "Adicional de hora extra (%)",
  rest_day_overtime_rate_percent: "Adicional de hora extra em folga ou feriado (%)",
  night_start: "Início do horário noturno",
  night_end: "Fim do horário noturno",
  night_additional_percent: "Adicional noturno (%)",
  night_reduced_hour: "Hora noturna menor (52 min 30 s contam como 1 hora)",
  night_extension: "Continuar o adicional noturno depois do fim do horário noturno",
  break_rules: "Intervalos obrigatórios",
  min_rest_between_journeys_hours: "Descanso mínimo entre um dia de trabalho e outro (horas)",
  max_daily_overtime_minutes: "Avisar quando as horas extras do dia passarem de (minutos)",
  journey_split_gap_hours: "Considerar um novo dia de trabalho após (horas sem bater o ponto)",
  duplicate_mark_window_seconds: "Ignorar a segunda batida feita em até (segundos)",
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
          Mudar as regras
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
                ? `Regras versão ${current.version}, valem desde ${dateBR(current.valid_from)}`
                : "Regras padrão do sistema"
            }
            footer="Quando você muda uma regra, ela vale a partir da data escolhida. Os dias anteriores continuam calculados com as regras da época."
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
            <details className="tech">
              <summary>Histórico de versões das regras</summary>
              <Group>
                {rules.data.versions.map((v) => (
                  <Row
                    key={v.id}
                    title={`Versão ${v.version}`}
                    subtitle={v.note}
                    value={`desde ${dateBR(v.valid_from)}`}
                  />
                ))}
              </Group>
            </details>
          )}
        </>
      )}

      <Group
        title={`Feriados de ${year}`}
        footer="Cadastre os feriados nacionais, estaduais e municipais que valem para a empresa toda ou só para uma unidade."
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
            placeholder="Nome do feriado"
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
    <Sheet title="Mudar as regras" open={open} onClose={onClose}>
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
          <Field label="Passa a valer em">
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
        <Field label="Por que está mudando? (ex.: nova convenção coletiva)">
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} />
        </Field>
        <ErrorText message={error} />
        <div className="actions">
          <button type="submit" disabled={pending}>
            Salvar as novas regras
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
  const files = usePaged(
    async (page) =>
      isAdmin
        ? listGeneratedFiles(companyId, page)
        : { count: 0, next: null, previous: null, results: [] },
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
      subtitle="Tudo o que você baixa aqui fica registrado no histórico de uso."
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
          subtitle="Horas a cumprir, trabalhadas, extras, devidas, noturnas e faltas (planilha)"
          accessory={
            <Download href={downloads.summary(companyId, period.from, period.to)}>
              Planilha
            </Download>
          }
        />
        <Row
          title="Batidas de ponto originais"
          subtitle="Todas as batidas de ponto originais; o CPF completo aparece só para administradores (planilha)"
          accessory={
            <Download href={downloads.records(companyId, period.from, period.to)}>
              Planilha
            </Download>
          }
        />
      </Group>
      {isAdmin && (
        <>
          <Group
            title="Arquivo para a fiscalização (AFD)"
            footer="Gerado por unidade. Ainda não tem assinatura digital, e o formato precisa ser conferido com o modelo oficial antes de ser entregue à fiscalização."
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
            title="Modelos de arquivo para a folha de pagamento"
            aside={
              <button className="plain" onClick={() => setCreatingProfile(true)}>
                Novo modelo
              </button>
            }
            footer="O arquivo da folha de pagamento só pode ser gerado de um período já fechado. Baixe na tela “Fechar o mês”."
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
              <Empty title="Nenhum modelo de folha de pagamento">
                <p>
                  Diga qual código do seu sistema de folha de pagamento corresponde a cada tipo de
                  hora (extra, noturna, falta…).
                </p>
              </Empty>
            )}
          </Group>
          <Group title="Arquivos gerados">
            {files.items.length ? (
              <table>
                <thead>
                  <tr>
                    <th>Tipo</th>
                    <th>Período</th>
                    <th>Gerado</th>
                    <th>Código de verificação</th>
                    <th>Avisos</th>
                  </tr>
                </thead>
                <tbody>
                  {files.items.map((f) => (
                    <tr key={f.id}>
                      <td>{f.kind === "afd" ? "Fiscalização (AFD)" : "Folha de pagamento"}</td>
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
            <LoadMore
              shown={files.items.length}
              total={files.count}
              hasMore={files.hasMore}
              loading={files.loading}
              onMore={files.loadMore}
            />
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
    <Sheet title="Modelo de folha de pagamento" open={open} onClose={onClose}>
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
          <Field label="Tipo de arquivo">
            <select value={format} onChange={(e) => setFormat(e.target.value as "csv" | "fixed")}>
              <option value="csv">Planilha (CSV)</option>
              <option value="fixed">Texto com colunas fixas (TXT)</option>
            </select>
          </Field>
          {Object.entries(events).map(([k, label]) => (
            <Field key={k} label={`Código para: ${label}`}>
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
            Salvar modelo
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
  const modules = useModules();
  const moduleAction = useAction();
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
    <Screen title="Dados da empresa">
      <Group
        title="Como o funcionário se identifica no tablet"
        padded
        footer={
          p?.engine
            ? `Reconhecimento facial: ${p.engine.name} ${p.engine.version}${p.engine.simulator ? " (versão de teste, não use com funcionários reais)" : ""}.`
            : "O reconhecimento facial ainda não foi configurado no sistema."
        }
      >
        {!p ? (
          <Loading />
        ) : (
          <div className="form-grid">
            <Field label="Como o funcionário se identifica">
              <select
                value={p.mode}
                onChange={(e) => void change({ mode: e.target.value as Policy["mode"] })}
              >
                <option value="registration">Só digitando a matrícula (menos seguro)</option>
                <option value="face">Reconhecimento facial (ou código liberado pelo gestor)</option>
              </select>
            </Field>
            <Field
              label="Como confirmar que é uma pessoa de verdade"
              hint="O teste simples (virar o rosto) barra uma foto parada, mas não é uma proteção certificada contra fraude."
            >
              <select
                value={p.face_liveness_policy}
                onChange={(e) =>
                  void change({
                    face_liveness_policy: e.target.value as Policy["face_liveness_policy"],
                  })
                }
              >
                <option value="certified">Só com proteção certificada contra fraude</option>
                <option value="basic_challenge">Aceitar o teste simples (virar o rosto)</option>
              </select>
            </Field>
            <Field
              label="Tablet sem internet"
              hint="Sem internet, só dá para bater o ponto pela matrícula. A batida fica marcada para revisão, e o comprovante sai quando o tablet voltar a ter internet."
            >
              <select
                value={p.offline_policy}
                onChange={(e) =>
                  void change({ offline_policy: e.target.value as Policy["offline_policy"] })
                }
              >
                <option value="disabled">Não permitir bater o ponto sem internet</option>
                <option value="registration_only">Permitir pela matrícula e revisar depois</option>
              </select>
            </Field>
          </div>
        )}
        <ErrorText message={error ?? policy.error} />
      </Group>
      <Group
        title="Situação da equipe (opcional)"
        padded
        footer="Mostra quem está disponível, em pausa ou fora, informado à mão pela equipe ou pelo gestor. Exige atualização constante e não registra o ponto de ninguém. Desligado, nada disso aparece; o que já foi informado fica guardado."
      >
        <label style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <input
            type="checkbox"
            checked={modules.availability}
            disabled={moduleAction.pending}
            onChange={(e) =>
              void moduleAction.run(async () => {
                await setAvailabilityEnabled(companyId, e.target.checked);
                modules.reload();
              })
            }
          />
          Usar a situação da equipe
        </label>
        <ErrorText message={moduleAction.error} />
      </Group>
      <Group title="Dados da empresa que aparecem no comprovante" padded>
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
    <Screen title="Plano e pagamentos" subtitle={b?.notice}>
      {!b ? (
        <Loading />
      ) : (
        <>
          <Group
            title="Situação"
            footer={sub?.sandbox ? "Ambiente de teste: nenhuma cobrança real é feita." : undefined}
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
            {sub && <Row title="Pago até" value={dateBR(sub.current_period_end)} />}
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
                    ? "A assinatura será cancelada no fim do período pago"
                    : "A assinatura renova sozinha"
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
                    {sub.cancel_at_period_end ? "Não cancelar" : "Cancelar no fim do período"}
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
                    <th>Vence em</th>
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
  // Operacoes sensiveis exigem login recente: se o servidor pedir, a senha e confirmada e a acao repetida.
  const [retry, setRetry] = useState<(() => Promise<void>) | null>(null);
  const [confirmPassword, setConfirmPassword] = useState("");
  const guarded = (action: () => Promise<void>) =>
    run(async () => {
      try {
        await action();
      } catch (e) {
        if (e instanceof ApiError && e.body.code === "reauth_required") {
          setRetry(() => action);
          return;
        }
        throw e;
      }
    });
  return (
    <Screen title="Minha conta" subtitle={me.email}>
      <Group
        title="Confirmação em duas etapas (mais segurança)"
        padded
        footer="Além da senha, você digita um código de 6 números que aparece no seu celular, em um aplicativo como o Google Authenticator ou o Microsoft Authenticator. Recomendado para quem administra a empresa."
      >
        {retry ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                await reauthenticate(confirmPassword);
                setConfirmPassword("");
                const again = retry;
                setRetry(null);
                await guarded(again);
              });
            }}
          >
            <p>Por segurança, confirme sua senha para continuar.</p>
            <Field label="Senha">
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </Field>
            <div className="actions">
              <button type="button" onClick={() => setRetry(null)}>
                Cancelar
              </button>
              <button type="submit" className="primary" disabled={pending}>
                Confirmar senha
              </button>
            </div>
          </form>
        ) : codes ? (
          <>
            <p>
              Guarde estes códigos de emergência em um lugar seguro (anote em papel). Se você perder
              o celular, cada um deles pode ser usado uma vez para entrar. Eles não serão mostrados
              de novo.
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
              void guarded(async () => {
                await disableMfa(password, code);
                setCode("");
                setPassword("");
                await session.refresh();
              });
            }}
          >
            <p>
              <Badge tone="tint">Ligada</Badge>
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
              <Field label="Código do aplicativo (ou código de emergência)">
                <input value={code} onChange={(e) => setCode(e.target.value)} required />
              </Field>
            </div>
            <div className="actions">
              <button type="submit" className="destructive" disabled={pending}>
                Desligar
              </button>
            </div>
          </form>
        ) : setup ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void guarded(async () => {
                setCodes((await confirmMfa(code)).recovery_codes);
                setSetup(null);
                setCode("");
              });
            }}
          >
            <p>
              No aplicativo, escolha “adicionar conta” e digite a chave abaixo. Depois, escreva aqui
              o código de 6 números que o aplicativo mostrar.
            </p>
            <p>
              Chave para digitar no aplicativo:{" "}
              <code style={{ fontSize: 15, letterSpacing: 1 }}>
                {setup.secret.match(/.{1,4}/g)?.join(" ")}
              </code>
            </p>
            <p>
              <a href={setup.otpauth_uri}>Tentar abrir direto no aplicativo</a>
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
                Ligar
              </button>
            </div>
          </form>
        ) : (
          <button
            className="primary"
            disabled={pending}
            onClick={() => void guarded(async () => setSetup(await startMfa()))}
          >
            Começar a configurar
          </button>
        )}
        <ErrorText message={error} />
      </Group>
      <Group title="Sair do sistema">
        <Row
          title="Encerrar o acesso neste aparelho"
          accessory={<button onClick={() => void session.signOut()}>Sair</button>}
        />
      </Group>
    </Screen>
  );
}
