import { useCallback, useEffect, useState } from "react";
import { IdentificationModePanel } from "./BiometricsActions";
import { errorMessage } from "./auth";
import type { Page } from "./operationsApi";
import {
  type Employer,
  KIND_LABELS,
  type RecordFilters,
  type TimeRecord,
  formatLocalTime,
  getEmployer,
  listTimeRecords,
  updateEmployer,
} from "./timeclockApi";

export function RecordsTab({ companyId }: { companyId: number }) {
  const [filters, setFilters] = useState<RecordFilters>({ from: "", to: "", page: 1 });
  const [data, setData] = useState<Page<TimeRecord> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    setData(null);
    listTimeRecords(companyId, filters)
      .then((value) => {
        if (current) {
          setData(value);
          setError(null);
        }
      })
      .catch((e) => {
        if (current) setError(errorMessage(e));
      });
    return () => {
      current = false;
    };
  }, [companyId, filters]);

  const set = (patch: Partial<RecordFilters>) => setFilters({ ...filters, page: 1, ...patch });
  const pages = data ? Math.max(1, Math.ceil(data.count / 25)) : 1;

  return (
    <div>
      <p>
        Marcações são registros originais e não podem ser editados nem apagados. Ajustes e
        justificativas são tratados à parte.
      </p>
      {error && <p role="alert">{error}</p>}
      <label>
        De
        <input type="date" value={filters.from} onChange={(e) => set({ from: e.target.value })} />
      </label>
      <label>
        Até
        <input type="date" value={filters.to} onChange={(e) => set({ to: e.target.value })} />
      </label>
      <p>{data ? `${data.count} marcação(ões)` : "Carregando…"}</p>
      <ul>
        {data?.results.map((r) => (
          <li key={r.id}>
            <strong>NSR {r.nsr}</strong> —{" "}
            {formatLocalTime(r.occurred_at, r.occurred_offset_minutes)} — {r.employee.registration}{" "}
            {r.employee.name} — {r.unit.name} / {r.device.name}
            {r.declared_kind && ` — ${KIND_LABELS[r.declared_kind]}`}
            {r.offline && " — registrada offline"}
            <code title={r.hash_sha256}> {r.hash_sha256.slice(0, 12)}…</code>
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
          disabled={!data?.next}
          onClick={() => setFilters({ ...filters, page: filters.page + 1 })}
        >
          Próxima
        </button>
      </p>
    </div>
  );
}

export function EmployerTab({ companyId, canEdit }: { companyId: number; canEdit: boolean }) {
  const [form, setForm] = useState<Employer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(() => {
    getEmployer(companyId)
      .then((value) => {
        setForm(value);
        setError(null);
      })
      .catch((e) => setError(errorMessage(e)));
  }, [companyId]);
  useEffect(load, [load]);

  if (!form) return error ? <p role="alert">{error}</p> : <p>Carregando…</p>;
  const set = (patch: Partial<Employer>) => {
    setSaved(false);
    setForm({ ...form, ...patch });
  };

  return (
    <>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          updateEmployer(companyId, form)
            .then((value) => {
              setForm(value);
              setSaved(true);
            })
            .catch((err) => setError(errorMessage(err)));
        }}
      >
        <p>Estes dados aparecem no Comprovante de Registro de Ponto. Alterações são auditadas.</p>
        {error && <p role="alert">{error}</p>}
        <label>
          Razão social ou nome
          <input
            value={form.legal_name}
            disabled={!canEdit}
            onChange={(e) => set({ legal_name: e.target.value })}
          />
        </label>
        <label>
          Tipo de documento
          <select
            value={form.tax_id_type}
            disabled={!canEdit}
            onChange={(e) => set({ tax_id_type: e.target.value as Employer["tax_id_type"] })}
          >
            <option value="">—</option>
            <option value="CNPJ">CNPJ</option>
            <option value="CPF">CPF</option>
          </select>
        </label>
        <label>
          Documento (somente números)
          <input
            value={form.tax_id}
            disabled={!canEdit}
            onChange={(e) => set({ tax_id: e.target.value })}
          />
        </label>
        <label>
          CEI/CAEPF/CNO (se houver)
          <input
            value={form.cei_caepf_cno}
            disabled={!canEdit}
            onChange={(e) => set({ cei_caepf_cno: e.target.value })}
          />
        </label>
        {canEdit && <button type="submit">Salvar dados do empregador</button>}
        {saved && <p role="status">Dados salvos.</p>}
      </form>
      <IdentificationModePanel companyId={companyId} canEdit={canEdit} />
    </>
  );
}
