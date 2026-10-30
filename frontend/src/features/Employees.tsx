import { useEffect, useState } from "react";
import { BiometricsActions } from "../BiometricsActions";
import { request } from "../http";
import { dateBR, isoDate } from "../lib/format";
import { useRouter } from "../lib/router";
import { useCompany } from "../lib/session";
import { useAction, useTask } from "../lib/task";
import {
  type Employee,
  changeAssignment,
  createEmployee,
  listEmployees,
  listSchedules,
  listSectors,
  listUnits,
  updateEmployee,
} from "../operationsApi";
import { Icon } from "../ui/icons";
import {
  Badge,
  Empty,
  ErrorText,
  Field,
  Group,
  Loading,
  Row,
  Screen,
  Segmented,
  Sheet,
} from "../ui/kit";
import { ImportTab } from "../Operations";
import { useModules } from "../lib/modules";
import { AvailabilityToggle } from "./Availability";

interface EmployeeDetail extends Employee {
  admission_date: string | null;
  access_email: string;
}
interface Interval<T> {
  id: number;
  valid_from: string;
  valid_to: string | null;
  unit?: { id: number; name: string };
  sector?: { id: number; name: string } | null;
  schedule?: T;
}

const emp = (c: number, id: number) => `/api/companies/${c}/employees/${id}`;

export function EmployeesScreen() {
  const { companyId, isAdmin } = useCompany();
  const modules = useModules();
  const router = useRouter();
  const [tab, setTab] = useState<"list" | "import">("list");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [unit, setUnit] = useState("");
  const [active, setActive] = useState("true");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => {
      setQuery(q);
      setPage(1);
    }, 250);
    return () => clearTimeout(t);
  }, [q]);
  const units = useTask(() => listUnits(companyId), [companyId]);
  const list = useTask(
    () => listEmployees(companyId, { q: query, unit, active, page }),
    [companyId, query, unit, active, page],
  );
  const pages = list.data ? Math.max(1, Math.ceil(list.data.count / 25)) : 1;

  return (
    <Screen
      title="Funcionários"
      subtitle={list.data ? `${list.data.count} encontrado(s)` : undefined}
      toolbar={
        <>
          {isAdmin && (
            <Segmented
              label="Visão"
              value={tab}
              onChange={setTab}
              options={[
                ["list", "Lista"],
                ["import", "Cadastrar vários de uma vez"],
              ]}
            />
          )}
          {isAdmin && tab === "list" && (
            <button className="primary" onClick={() => setCreating(true)}>
              <Icon name="plus" size={16} /> Novo funcionário
            </button>
          )}
        </>
      }
    >
      {tab === "import" ? (
        <Group
          padded
          footer="Serve só para cadastrar pessoas novas. Primeiro veja a prévia: se alguma linha tiver erro, nada é cadastrado."
        >
          <div className="legacy">
            <ImportTab companyId={companyId} />
          </div>
        </Group>
      ) : (
        <>
          <div className="toolbar" style={{ marginBottom: 14 }}>
            <input
              type="search"
              aria-label="Buscar"
              placeholder="Digite o nome ou a matrícula"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <select
              aria-label="Filtrar por unidade"
              value={unit}
              onChange={(e) => {
                setUnit(e.target.value);
                setPage(1);
              }}
            >
              <option value="">Todas as unidades</option>
              {units.data?.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
            </select>
            <Segmented
              label="Situação"
              value={active}
              onChange={(v) => {
                setActive(v);
                setPage(1);
              }}
              options={[
                ["true", "Ativos"],
                ["false", "Inativos"],
                ["", "Todos"],
              ]}
            />
          </div>
          <Group
            footer={
              pages > 1 && (
                <span className="toolbar">
                  <button disabled={page <= 1} onClick={() => setPage(page - 1)}>
                    Anterior
                  </button>
                  Página {page} de {pages}
                  <button disabled={page >= pages} onClick={() => setPage(page + 1)}>
                    Próxima
                  </button>
                </span>
              )
            }
          >
            {list.loading && !list.data ? (
              <Loading />
            ) : list.error ? (
              <ErrorText message={list.error} />
            ) : list.data?.results.length ? (
              list.data.results.map((e) => (
                <Row
                  key={e.id}
                  title={e.full_name}
                  subtitle={`Matrícula ${e.registration}${e.unit ? `, ${e.unit.name}${e.sector ? ` / ${e.sector.name}` : ""}` : ", sem unidade definida"}`}
                  accessory={!e.is_active && <Badge>Inativo</Badge>}
                  onClick={() => router.push({ screen: "employee", id: e.id })}
                />
              ))
            ) : (
              <Empty
                title={query ? "Nenhum funcionário encontrado" : "Nenhum funcionário cadastrado"}
              >
                {isAdmin && !query && (
                  <p>Cadastre uma pessoa de cada vez ou várias de uma vez, com uma planilha.</p>
                )}
              </Empty>
            )}
          </Group>
        </>
      )}
      {!modules.availability && <AvailabilityToggle />}
      <CreateSheet
        open={creating}
        onClose={() => setCreating(false)}
        onDone={(id) => {
          setCreating(false);
          router.push({ screen: "employee", id });
        }}
      />
    </Screen>
  );
}

function CreateSheet({
  open,
  onClose,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  onDone: (id: number) => void;
}) {
  const { companyId } = useCompany();
  const [form, setForm] = useState({ registration: "", name: "", cpf: "" });
  const { pending, error, run } = useAction();
  return (
    <Sheet title="Novo funcionário" open={open} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            const created = await createEmployee(companyId, form.registration, form.name, form.cpf);
            setForm({ registration: "", name: "", cpf: "" });
            onDone(created.id);
          });
        }}
      >
        <div className="form-grid">
          <Field label="Matrícula" hint="Não pode ser alterada depois.">
            <input
              value={form.registration}
              onChange={(e) => setForm({ ...form, registration: e.target.value })}
              required
              maxLength={30}
            />
          </Field>
          <Field label="Nome completo">
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
              maxLength={200}
            />
          </Field>
          <Field
            label="CPF (opcional)"
            hint="Aparece no comprovante de ponto e nos arquivos da fiscalização."
          >
            <input
              value={form.cpf}
              onChange={(e) => setForm({ ...form, cpf: e.target.value })}
              inputMode="numeric"
            />
          </Field>
        </div>
        <ErrorText message={error} />
        <div className="actions">
          <button type="submit" disabled={pending}>
            Cadastrar
          </button>
        </div>
      </form>
    </Sheet>
  );
}

export function EmployeeDetailScreen({ id }: { id: number }) {
  const { companyId, isAdmin } = useCompany();
  const router = useRouter();
  const employee = useTask(
    () => request<EmployeeDetail>("GET", `${emp(companyId, id)}/`),
    [companyId, id],
  );
  const assignments = useTask(
    () => request<Interval<never>[]>("GET", `${emp(companyId, id)}/assignments/`),
    [companyId, id],
  );
  const schedules = useTask(
    () =>
      request<Interval<{ id: number; name: string }>[]>("GET", `${emp(companyId, id)}/schedules/`),
    [companyId, id],
  );
  const [sheet, setSheet] = useState<"assignment" | "schedule" | "edit" | null>(null);
  const { error, run } = useAction();
  const e = employee.data;
  if (!e)
    return (
      <Screen title="Funcionário">
        {employee.error ? <ErrorText message={employee.error} /> : <Loading />}
      </Screen>
    );
  const reload = () => {
    employee.reload();
    assignments.reload();
    schedules.reload();
  };

  return (
    <Screen
      title={e.full_name}
      subtitle={`Matrícula ${e.registration}`}
      toolbar={
        <>
          <button onClick={() => router.push({ screen: "timesheet", employeeId: e.id })}>
            <Icon name="sheet" size={16} /> Folha de ponto
          </button>
          {isAdmin && <button onClick={() => setSheet("edit")}>Editar</button>}
          {isAdmin && (
            <button
              className={e.is_active ? "destructive" : "primary"}
              onClick={() =>
                void run(async () => {
                  await updateEmployee(companyId, e.id, { is_active: !e.is_active });
                  reload();
                })
              }
            >
              {e.is_active ? "Inativar" : "Reativar"}
            </button>
          )}
        </>
      }
    >
      <ErrorText message={error} />
      <Group title="Cadastro">
        <Row title="Situação" value={e.is_active ? "Ativo" : "Inativo"} />
        <Row title="CPF" value={e.cpf || "Não informado"} />
        <Row title="Admissão" value={dateBR(e.admission_date)} />
        <Row
          title="E-mail para acessar o sistema"
          value={e.access_email || "Ainda não tem acesso"}
        />
      </Group>
      <Group
        title="Unidade e setor"
        aside={
          isAdmin && (
            <button className="plain" onClick={() => setSheet("assignment")}>
              Mudar de unidade ou setor
            </button>
          )
        }
        footer="Cada mudança vale a partir de uma data. O que já passou não é alterado."
      >
        {assignments.data?.length ? (
          assignments.data.map((a) => (
            <Row
              key={a.id}
              title={`${a.unit?.name}${a.sector ? ` / ${a.sector.name}` : ""}`}
              value={`${dateBR(a.valid_from)} a ${a.valid_to ? dateBR(a.valid_to) : "hoje"}`}
            />
          ))
        ) : (
          <Empty title="Sem unidade definida" />
        )}
      </Group>
      <Group
        title="Horário de trabalho"
        aside={
          isAdmin && (
            <button className="plain" onClick={() => setSheet("schedule")}>
              Definir horário de trabalho
            </button>
          )
        }
      >
        {schedules.data?.length ? (
          schedules.data.map((s) => (
            <Row
              key={s.id}
              title={s.schedule?.name}
              value={`${dateBR(s.valid_from)} a ${s.valid_to ? dateBR(s.valid_to) : "hoje"}`}
            />
          ))
        ) : (
          <Empty title="Nenhum horário de trabalho definido">
            <p>
              Sem horário de trabalho, todos os dias contam como folga e todas as horas trabalhadas
              como extras.
            </p>
          </Empty>
        )}
      </Group>
      <Group
        title="Identificação no tablet"
        padded
        footer="Autorização para usar o rosto, cadastro do rosto e código para bater o ponto quando o reconhecimento não funcionar."
      >
        <div className="legacy">
          <BiometricsActions
            companyId={companyId}
            employeeId={e.id}
            employeeName={e.full_name}
            canEdit={isAdmin}
          />
        </div>
      </Group>
      <AssignmentSheet
        open={sheet === "assignment"}
        employeeId={e.id}
        onClose={() => setSheet(null)}
        onDone={() => {
          setSheet(null);
          reload();
        }}
      />
      <ScheduleSheet
        open={sheet === "schedule"}
        employeeId={e.id}
        onClose={() => setSheet(null)}
        onDone={() => {
          setSheet(null);
          reload();
        }}
      />
      <EditSheet
        open={sheet === "edit"}
        employee={e}
        onClose={() => setSheet(null)}
        onDone={() => {
          setSheet(null);
          reload();
        }}
      />
    </Screen>
  );
}

function AssignmentSheet({
  open,
  employeeId,
  onClose,
  onDone,
}: {
  open: boolean;
  employeeId: number;
  onClose: () => void;
  onDone: () => void;
}) {
  const { companyId } = useCompany();
  const units = useTask(() => listUnits(companyId), [companyId]);
  const sectors = useTask(() => listSectors(companyId), [companyId]);
  const [unit, setUnit] = useState("");
  const [sector, setSector] = useState("");
  const [from, setFrom] = useState(isoDate(new Date()));
  const { pending, error, run } = useAction();
  return (
    <Sheet title="Mudar de unidade ou setor" open={open} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            await changeAssignment(
              companyId,
              employeeId,
              Number(unit),
              sector ? Number(sector) : null,
              from,
            );
            onDone();
          });
        }}
      >
        <div className="form-grid">
          <Field label="Unidade">
            <select
              value={unit}
              onChange={(e) => {
                setUnit(e.target.value);
                setSector("");
              }}
              required
            >
              <option value="">Escolha…</option>
              {units.data
                ?.filter((u) => u.is_active)
                .map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name}
                  </option>
                ))}
            </select>
          </Field>
          <Field label="Setor">
            <select value={sector} onChange={(e) => setSector(e.target.value)}>
              <option value="">Sem setor</option>
              {sectors.data
                ?.filter((s) => s.is_active && String(s.unit) === unit)
                .map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
            </select>
          </Field>
          <Field label="Vale a partir de">
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} required />
          </Field>
        </div>
        <ErrorText message={error} />
        <div className="actions">
          <button type="submit" disabled={pending}>
            Salvar
          </button>
        </div>
      </form>
    </Sheet>
  );
}

function ScheduleSheet({
  open,
  employeeId,
  onClose,
  onDone,
}: {
  open: boolean;
  employeeId: number;
  onClose: () => void;
  onDone: () => void;
}) {
  const { companyId } = useCompany();
  const list = useTask(() => listSchedules(companyId), [companyId]);
  const [schedule, setSchedule] = useState("");
  const [from, setFrom] = useState(isoDate(new Date()));
  const { pending, error, run } = useAction();
  return (
    <Sheet title="Definir horário de trabalho" open={open} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            await request("POST", `${emp(companyId, employeeId)}/schedules/`, {
              schedule: Number(schedule),
              valid_from: from,
            });
            onDone();
          });
        }}
      >
        <div className="form-grid">
          <Field label="Horário de trabalho">
            <select value={schedule} onChange={(e) => setSchedule(e.target.value)} required>
              <option value="">Escolha…</option>
              {list.data
                ?.filter((s) => s.is_active)
                .map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
            </select>
          </Field>
          <Field label="Vale a partir de">
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} required />
          </Field>
        </div>
        <ErrorText message={error} />
        <div className="actions">
          <button type="submit" disabled={pending}>
            Salvar
          </button>
        </div>
      </form>
    </Sheet>
  );
}

function EditSheet({
  open,
  employee,
  onClose,
  onDone,
}: {
  open: boolean;
  employee: EmployeeDetail;
  onClose: () => void;
  onDone: () => void;
}) {
  const { companyId } = useCompany();
  const [form, setForm] = useState({
    full_name: employee.full_name,
    cpf: "",
    admission_date: employee.admission_date ?? "",
    access_email: employee.access_email,
  });
  const { pending, error, run } = useAction();
  return (
    <Sheet title="Editar cadastro" open={open} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            const changes: Record<string, unknown> = {
              full_name: form.full_name,
              admission_date: form.admission_date || null,
            };
            // Sem acesso ainda: o vínculo é feito pelo botão "Convidar e dar acesso".
            if (employee.access_email) changes.access_email = form.access_email;
            if (form.cpf) changes.cpf = form.cpf;
            await request("PATCH", `${emp(companyId, employee.id)}/`, changes);
            onDone();
          });
        }}
      >
        <div className="form-grid">
          <Field label="Nome completo">
            <input
              value={form.full_name}
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              required
            />
          </Field>
          <Field label="Novo CPF" hint="Deixe em branco para manter o atual.">
            <input
              value={form.cpf}
              onChange={(e) => setForm({ ...form, cpf: e.target.value })}
              inputMode="numeric"
            />
          </Field>
          <Field label="Admissão">
            <input
              type="date"
              value={form.admission_date}
              onChange={(e) => setForm({ ...form, admission_date: e.target.value })}
            />
          </Field>
          <Field
            label="E-mail para acessar o sistema"
            hint={
              employee.access_email
                ? "Para trocar, informe o e-mail de quem já tem acesso nesta empresa."
                : "A pessoa recebe um convite por e-mail para criar a senha e vê só o próprio ponto."
            }
          >
            <input
              type="email"
              value={form.access_email}
              onChange={(e) => setForm({ ...form, access_email: e.target.value })}
            />
          </Field>
          {!employee.access_email && (
            <div className="actions" style={{ alignSelf: "end" }}>
              <button
                type="button"
                disabled={pending || !form.access_email.includes("@")}
                onClick={() =>
                  void run(async () => {
                    await request("POST", `${emp(companyId, employee.id)}/access/`, {
                      email: form.access_email,
                    });
                    onDone();
                  })
                }
              >
                Convidar e dar acesso
              </button>
            </div>
          )}
        </div>
        <ErrorText message={error} />
        <div className="actions">
          <button type="submit" disabled={pending}>
            Salvar
          </button>
        </div>
      </form>
    </Sheet>
  );
}
