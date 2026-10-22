import { useCallback, useEffect, useRef, useState } from "react";
import { BiometricsActions } from "./BiometricsActions";
import { DevicesTab } from "./DevicesTab";
import { EmployerTab, RecordsTab } from "./TimeclockTab";
import { errorMessage } from "./auth";
import {
  type Employee,
  type EmployeeFilters,
  type ImportResult,
  type Page,
  type Schedule,
  type Sector,
  type Unit,
  changeAssignment,
  createEmployee,
  createSchedule,
  createSector,
  createUnit,
  importEmployees,
  listEmployees,
  listSchedules,
  listSectors,
  listUnits,
  updateEmployee,
  updateSector,
  updateUnit,
} from "./operationsApi";

type Tab = "units" | "employees" | "import" | "schedules" | "devices" | "records" | "employer";
const TABS: [Tab, string][] = [
  ["records", "Marcações"],
  ["employees", "Funcionários"],
  ["units", "Unidades e setores"],
  ["schedules", "Jornadas"],
  ["devices", "Tablets"],
  ["import", "Importação"],
  ["employer", "Empregador"],
];
const WEEKDAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];

function useLoader<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const reload = useCallback(() => {
    const current = ++generation.current;
    setData(null);
    setError(null);
    fn()
      .then((value) => {
        if (current === generation.current) setData(value);
      })
      .catch((e) => {
        if (current === generation.current) setError(errorMessage(e));
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    const tracker = generation;
    reload();
    return () => {
      tracker.current++;
    };
  }, [reload]);
  return { data, error, reload };
}

function useRunner(after: () => void) {
  const [error, setError] = useState<string | null>(null);
  const run = (fn: () => Promise<unknown>) => {
    setError(null);
    fn()
      .then(after)
      .catch((e) => setError(errorMessage(e)));
  };
  return { error, run };
}

const Alert = ({ message }: { message: string | null }) =>
  message ? <p role="alert">{message}</p> : null;

export function Operations({ companyId, canEdit }: { companyId: number; canEdit: boolean }) {
  return (
    <OperationsPanel key={`${companyId}:${canEdit}`} companyId={companyId} canEdit={canEdit} />
  );
}

function OperationsPanel({ companyId, canEdit }: { companyId: number; canEdit: boolean }) {
  const [tab, setTab] = useState<Tab>("employees");
  return (
    <section>
      <nav aria-label="Operação">
        {TABS.filter(([key]) => canEdit || key !== "import").map(([key, label]) => (
          <button key={key} aria-pressed={tab === key} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </nav>
      {tab === "employees" && <EmployeesTab companyId={companyId} canEdit={canEdit} />}
      {tab === "units" && <UnitsTab companyId={companyId} canEdit={canEdit} />}
      {tab === "schedules" && <SchedulesTab companyId={companyId} canEdit={canEdit} />}
      {tab === "devices" && <DevicesTab companyId={companyId} canEdit={canEdit} />}
      {tab === "records" && <RecordsTab companyId={companyId} />}
      {tab === "employer" && <EmployerTab companyId={companyId} canEdit={canEdit} />}
      {tab === "import" && canEdit && <ImportTab companyId={companyId} />}
    </section>
  );
}

function UnitsTab({ companyId, canEdit }: { companyId: number; canEdit: boolean }) {
  const units = useLoader(() => listUnits(companyId), [companyId]);
  const sectors = useLoader(() => listSectors(companyId), [companyId]);
  const refresh = () => {
    units.reload();
    sectors.reload();
  };
  const { error, run } = useRunner(refresh);
  const [unitName, setUnitName] = useState("");
  const [sectorName, setSectorName] = useState("");
  const [sectorUnit, setSectorUnit] = useState("");

  return (
    <div>
      <Alert message={error ?? units.error ?? sectors.error} />
      <ul>
        {units.data?.map((u: Unit) => (
          <li key={u.id}>
            <strong>{u.name}</strong>
            {u.is_active ? "" : " [inativa]"}
            {canEdit && (
              <button
                onClick={() => run(() => updateUnit(companyId, u.id, { is_active: !u.is_active }))}
              >
                {u.is_active ? "Inativar" : "Reativar"}
              </button>
            )}
            <ul>
              {sectors.data
                ?.filter((s: Sector) => s.unit === u.id)
                .map((s: Sector) => (
                  <li key={s.id}>
                    {s.name}
                    {s.is_active ? "" : " [inativo]"}
                    {canEdit && (
                      <button
                        onClick={() =>
                          run(() => updateSector(companyId, s.id, { is_active: !s.is_active }))
                        }
                      >
                        {s.is_active ? "Inativar" : "Reativar"}
                      </button>
                    )}
                  </li>
                ))}
            </ul>
          </li>
        ))}
      </ul>
      {canEdit && (
        <>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              run(async () => {
                await createUnit(companyId, unitName);
                setUnitName("");
              });
            }}
          >
            <input
              aria-label="Nome da unidade"
              value={unitName}
              onChange={(e) => setUnitName(e.target.value)}
              required
            />
            <button type="submit">Adicionar unidade</button>
          </form>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              run(async () => {
                await createSector(companyId, sectorName, Number(sectorUnit));
                setSectorName("");
              });
            }}
          >
            <select
              aria-label="Unidade do setor"
              value={sectorUnit}
              onChange={(e) => setSectorUnit(e.target.value)}
              required
            >
              <option value="">Unidade…</option>
              {units.data?.map((u: Unit) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
            </select>
            <input
              aria-label="Nome do setor"
              value={sectorName}
              onChange={(e) => setSectorName(e.target.value)}
              required
            />
            <button type="submit">Adicionar setor</button>
          </form>
        </>
      )}
    </div>
  );
}

function EmployeesTab({ companyId, canEdit }: { companyId: number; canEdit: boolean }) {
  const [filters, setFilters] = useState<EmployeeFilters>({ q: "", unit: "", active: "", page: 1 });
  const units = useLoader(() => listUnits(companyId), [companyId]);
  const list = useLoader<Page<Employee>>(
    () => listEmployees(companyId, filters),
    [companyId, filters],
  );
  const { error, run } = useRunner(list.reload);
  const [form, setForm] = useState({ registration: "", name: "", cpf: "" });
  const [moving, setMoving] = useState<number | null>(null);
  const [move, setMove] = useState({ unit: "", sector: "", from: "" });
  const sectors = useLoader(() => listSectors(companyId), [companyId]);

  const set = (patch: Partial<EmployeeFilters>) => setFilters({ ...filters, page: 1, ...patch });
  const pages = list.data ? Math.max(1, Math.ceil(list.data.count / 25)) : 1;

  return (
    <div>
      <Alert message={error ?? list.error ?? units.error ?? sectors.error} />
      <input
        aria-label="Buscar"
        placeholder="Nome ou matrícula"
        value={filters.q}
        onChange={(e) => set({ q: e.target.value })}
      />
      <select
        aria-label="Filtrar por unidade"
        value={filters.unit}
        onChange={(e) => set({ unit: e.target.value })}
      >
        <option value="">Todas as unidades</option>
        {units.data?.map((u: Unit) => (
          <option key={u.id} value={u.id}>
            {u.name}
          </option>
        ))}
      </select>
      <select
        aria-label="Situação"
        value={filters.active}
        onChange={(e) => set({ active: e.target.value })}
      >
        <option value="">Todos</option>
        <option value="true">Ativos</option>
        <option value="false">Inativos</option>
      </select>
      <p>{list.data ? `${list.data.count} funcionário(s)` : "Carregando…"}</p>
      <ul>
        {list.data?.results.map((e) => (
          <li key={e.id}>
            {e.registration} — {e.full_name} {e.cpf && `(${e.cpf})`} —{" "}
            {e.unit?.name ?? "sem lotação"}
            {e.sector && ` / ${e.sector.name}`}
            {e.is_active ? "" : " [inativo]"}
            {canEdit && (
              <>
                <button
                  onClick={() =>
                    run(() => updateEmployee(companyId, e.id, { is_active: !e.is_active }))
                  }
                >
                  {e.is_active ? "Inativar" : "Reativar"}
                </button>
                <button onClick={() => setMoving(moving === e.id ? null : e.id)}>
                  Alterar lotação
                </button>
              </>
            )}
            {e.is_active && (
              <BiometricsActions
                companyId={companyId}
                employeeId={e.id}
                employeeName={e.full_name}
                canEdit={canEdit}
              />
            )}
            {canEdit && moving === e.id && (
              <form
                onSubmit={(ev) => {
                  ev.preventDefault();
                  run(async () => {
                    await changeAssignment(
                      companyId,
                      e.id,
                      Number(move.unit),
                      move.sector ? Number(move.sector) : null,
                      move.from,
                    );
                    setMoving(null);
                  });
                }}
              >
                <select
                  aria-label="Nova unidade"
                  value={move.unit}
                  onChange={(ev) => setMove({ ...move, unit: ev.target.value, sector: "" })}
                  required
                >
                  <option value="">Unidade…</option>
                  {units.data
                    ?.filter((u: Unit) => u.is_active)
                    .map((u: Unit) => (
                      <option key={u.id} value={u.id}>
                        {u.name}
                      </option>
                    ))}
                </select>
                <select
                  aria-label="Novo setor"
                  value={move.sector}
                  onChange={(ev) => setMove({ ...move, sector: ev.target.value })}
                >
                  <option value="">Sem setor</option>
                  {sectors.data
                    ?.filter((s: Sector) => s.is_active && String(s.unit) === move.unit)
                    .map((s: Sector) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                </select>
                <input
                  aria-label="Vigente a partir de"
                  type="date"
                  value={move.from}
                  onChange={(ev) => setMove({ ...move, from: ev.target.value })}
                  required
                />
                <button type="submit">Confirmar</button>
              </form>
            )}
          </li>
        ))}
      </ul>
      <p>
        <button
          disabled={filters.page <= 1}
          onClick={() => setFilters({ ...filters, page: filters.page - 1 })}
        >
          Anterior
        </button>{" "}
        Página {filters.page} de {pages}{" "}
        <button
          disabled={!list.data?.next}
          onClick={() => setFilters({ ...filters, page: filters.page + 1 })}
        >
          Próxima
        </button>
      </p>
      {canEdit && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run(async () => {
              await createEmployee(companyId, form.registration, form.name, form.cpf);
              setForm({ registration: "", name: "", cpf: "" });
            });
          }}
        >
          <h4>Novo funcionário</h4>
          <input
            aria-label="Matrícula"
            value={form.registration}
            onChange={(e) => setForm({ ...form, registration: e.target.value })}
            required
          />
          <input
            aria-label="Nome completo"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
          />
          <input
            aria-label="CPF (opcional)"
            value={form.cpf}
            onChange={(e) => setForm({ ...form, cpf: e.target.value })}
          />
          <button type="submit">Cadastrar</button>
        </form>
      )}
    </div>
  );
}

function SchedulesTab({ companyId, canEdit }: { companyId: number; canEdit: boolean }) {
  const list = useLoader<Schedule[]>(() => listSchedules(companyId), [companyId]);
  const { error, run } = useRunner(list.reload);
  const [name, setName] = useState("");
  const [start, setStart] = useState("08:00");
  const [end, setEnd] = useState("17:00");
  const [brk, setBrk] = useState("60");
  const [days, setDays] = useState<number[]>([0, 1, 2, 3, 4]);

  return (
    <div>
      <Alert message={error ?? list.error} />
      <ul>
        {list.data?.map((s) => (
          <li key={s.id}>
            {s.name}:{" "}
            {s.days
              .map(
                (d) =>
                  `${WEEKDAYS[d.weekday]} ${d.start_time.slice(0, 5)}–${d.end_time.slice(0, 5)}`,
              )
              .join(", ")}
          </li>
        ))}
      </ul>
      {canEdit && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run(async () => {
              await createSchedule(
                companyId,
                name,
                days.map((weekday) => ({
                  weekday,
                  start_time: start,
                  end_time: end,
                  break_minutes: Number(brk),
                })),
              );
              setName("");
            });
          }}
        >
          <h4>Nova jornada (uma jornada atribuída não pode mais ser alterada)</h4>
          <input
            aria-label="Nome da jornada"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <input
            aria-label="Início"
            type="time"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            required
          />
          <input
            aria-label="Fim"
            type="time"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            required
          />
          <input
            aria-label="Intervalo (min)"
            type="number"
            min={0}
            max={480}
            value={brk}
            onChange={(e) => setBrk(e.target.value)}
          />
          {WEEKDAYS.map((label, i) => (
            <label key={label}>
              <input
                type="checkbox"
                checked={days.includes(i)}
                onChange={() =>
                  setDays(days.includes(i) ? days.filter((d) => d !== i) : [...days, i])
                }
              />
              {label}
            </label>
          ))}
          <button type="submit" disabled={days.length === 0}>
            Criar jornada
          </button>
        </form>
      )}
    </div>
  );
}

function ImportTab({ companyId }: { companyId: number }) {
  const [csv, setCsv] = useState("matricula,nome,cpf,unidade,setor,inicio\n");
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [previewCsv, setPreviewCsv] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const send = (commit: boolean) => {
    setPending(true);
    setPreviewCsv(null);
    setError(null);
    importEmployees(companyId, csv, commit)
      .then((value) => {
        setResult(value);
        if (!commit && value.errors.length === 0) setPreviewCsv(csv);
      })
      .catch((e) => {
        setResult(null);
        setError(errorMessage(e));
      })
      .finally(() => setPending(false));
  };

  return (
    <div>
      <p>
        Colunas: matricula, nome (obrigatórias); cpf, unidade, setor, inicio (opcionais). A
        importação grava tudo ou nada.
      </p>
      <textarea
        aria-label="Conteúdo CSV"
        rows={8}
        cols={70}
        value={csv}
        disabled={pending}
        onChange={(e) => {
          setCsv(e.target.value);
          setPreviewCsv(null);
          setResult(null);
        }}
      />
      <div>
        <button disabled={pending} onClick={() => send(false)}>
          Pré-visualizar
        </button>
        <button disabled={pending || previewCsv !== csv} onClick={() => send(true)}>
          Importar
        </button>
      </div>
      <Alert message={error} />
      {result && (
        <div role="status">
          {result.total} linha(s): {result.valid} válida(s), {result.errors.length} erro(s).
          {result.committed > 0 && ` ${result.committed} funcionário(s) importado(s).`}
          <ul>
            {result.errors.map((e, i) => (
              <li key={i}>
                Linha {e.line} ({e.field}): {e.message}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
