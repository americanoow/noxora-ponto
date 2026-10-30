import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage } from "./auth";
import {
  type ImportResult,
  type Schedule,
  type Sector,
  type Unit,
  createSchedule,
  createSector,
  createUnit,
  importEmployees,
  listSchedules,
  listSectors,
  listUnits,
  updateSector,
  updateUnit,
} from "./operationsApi";

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

export function UnitsTab({ companyId, canEdit }: { companyId: number; canEdit: boolean }) {
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
            {u.is_active ? "" : " (inativa)"}
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
                    {s.is_active ? "" : " (inativo)"}
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

export function SchedulesTab({ companyId, canEdit }: { companyId: number; canEdit: boolean }) {
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
          <h4>
            Novo horário de trabalho (depois que alguém passar a usar, não será possível editar)
          </h4>
          <input
            aria-label="Nome do horário de trabalho (ex.: Comercial)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <input
            aria-label="Hora de entrada"
            type="time"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            required
          />
          <input
            aria-label="Hora de saída"
            type="time"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            required
          />
          <input
            aria-label="Tempo de intervalo (minutos)"
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
            Criar horário de trabalho
          </button>
        </form>
      )}
    </div>
  );
}

export function ImportTab({ companyId }: { companyId: number }) {
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
        Cole aqui os dados da planilha, uma pessoa por linha, com as colunas separadas por vírgula:
        matricula, nome (obrigatórias); cpf, unidade, setor, inicio (opcionais). Ou tudo é
        cadastrado, ou nada.
      </p>
      <textarea
        aria-label="Dados da planilha"
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
          Ver prévia
        </button>
        <button disabled={pending || previewCsv !== csv} onClick={() => send(true)}>
          Cadastrar todos
        </button>
      </div>
      <Alert message={error} />
      {result && (
        <div role="status">
          {result.total} linha(s): {result.valid} correta(s), {result.errors.length} com erro.
          {result.committed > 0 && ` ${result.committed} funcionário(s) cadastrado(s).`}
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
