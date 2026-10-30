import { useCallback, useEffect, useState } from "react";
import { downloads } from "./api/operational";
import { IdentificationModePanel } from "./BiometricsActions";
import { isoDate, monthRange } from "./lib/format";
import { Download } from "./ui/kit";
import { errorMessage } from "./auth";
import type { Page } from "./operationsApi";
import {
  type Employer,
  KIND_LABELS,
  SYNC_FLAG_LABELS,
  type RecordFilters,
  type TimeRecord,
  formatLocalTime,
  getEmployer,
  listTimeRecords,
  updateEmployer,
} from "./timeclockApi";

export function RecordsTab({
  companyId,
  from = "",
  to = "",
  onPeriod,
}: {
  companyId: number;
  /** Período inicial (vem da aba anterior) e aviso quando o usuário muda as datas. */
  from?: string;
  to?: string;
  onPeriod?: (from: string, to: string) => void;
}) {
  const [filters, setFilters] = useState<RecordFilters>({
    from,
    to,
    offline: "",
    page: 1,
  });
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

  const set = (patch: Partial<RecordFilters>) => {
    const next = { ...filters, page: 1, ...patch };
    setFilters(next);
    if (("from" in patch || "to" in patch) && onPeriod) onPeriod(next.from, next.to);
  };
  const month = monthRange(isoDate(new Date()));
  const sheetFrom = filters.from || month.from;
  const sheetTo = filters.to || month.to;
  const pages = data ? Math.max(1, Math.ceil(data.count / 25)) : 1;

  return (
    <div>
      <p>
        As batidas de ponto não podem ser editadas nem apagadas. Correções e justificativas são
        feitas por pedidos, que ficam registrados à parte.
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
      <label>
        Como foi feita
        <select
          value={filters.offline}
          onChange={(e) => set({ offline: e.target.value as RecordFilters["offline"] })}
        >
          <option value="">Todas</option>
          <option value="false">Com internet</option>
          <option value="true">Sem internet (enviadas depois)</option>
        </select>
      </label>
      <p>
        {data ? `${data.count} batida(s)` : "Carregando…"}{" "}
        <Download href={downloads.records(companyId, sheetFrom, sheetTo)}>
          Planilha das batidas ({sheetFrom.split("-").reverse().join("/")} a{" "}
          {sheetTo.split("-").reverse().join("/")})
        </Download>
      </p>
      <ul>
        {data?.results.map((r) => (
          <li key={r.id}>
            <strong>Registro nº {r.nsr}</strong> —{" "}
            {formatLocalTime(r.occurred_at, r.occurred_offset_minutes)} — {r.employee.registration}{" "}
            {r.employee.name} — {r.unit.name} / {r.device.name}
            {r.declared_kind && ` — ${KIND_LABELS[r.declared_kind]}`}
            {r.offline && " — feita sem internet"}
            {(r.sync_flags ?? []).length > 0 && (
              <span role="note">
                {" "}
                — precisa de revisão:{" "}
                {(r.sync_flags ?? []).map((f) => SYNC_FLAG_LABELS[f] ?? f).join("; ")}
              </span>
            )}
            <code title={`Código de verificação: ${r.hash_sha256}`}>
              {" "}
              {r.hash_sha256.slice(0, 12)}…
            </code>
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
        <p>
          Estes dados aparecem no comprovante de ponto. Toda mudança fica registrada no histórico.
        </p>
        {error && <p role="alert">{error}</p>}
        <label>
          Nome da empresa (razão social)
          <input
            value={form.legal_name}
            disabled={!canEdit}
            onChange={(e) => set({ legal_name: e.target.value })}
          />
        </label>
        <label>
          Tipo de documento da empresa
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
          Número do documento (só números)
          <input
            value={form.tax_id}
            disabled={!canEdit}
            onChange={(e) => set({ tax_id: e.target.value })}
          />
        </label>
        <label>
          Número CEI, CAEPF ou CNO (se tiver)
          <input
            value={form.cei_caepf_cno}
            disabled={!canEdit}
            onChange={(e) => set({ cei_caepf_cno: e.target.value })}
          />
        </label>
        {canEdit && <button type="submit">Salvar dados da empresa</button>}
        {saved && <p role="status">Dados salvos.</p>}
      </form>
      <IdentificationModePanel companyId={companyId} canEdit={canEdit} />
    </>
  );
}
