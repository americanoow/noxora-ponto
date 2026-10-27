import { useEffect, useState } from "react";
import { useCompany } from "../lib/session";
import { useTask } from "../lib/task";
import { listEmployees } from "../operationsApi";

/** Busca de funcionário por nome ou matrícula (escopo do usuário aplicado pela API). */
export function EmployeePicker({
  value,
  onChange,
}: {
  value: number | undefined;
  onChange: (id: number, name: string) => void;
}) {
  const { companyId } = useCompany();
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query), 250);
    return () => clearTimeout(t);
  }, [query]);
  const list = useTask(
    () => listEmployees(companyId, { q: debounced, unit: "", active: "true", page: 1 }),
    [companyId, debounced],
  );
  return (
    <span className="toolbar">
      <input
        type="search"
        aria-label="Buscar funcionário"
        placeholder="Buscar funcionário"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        style={{ width: 180 }}
      />
      <select
        aria-label="Funcionário"
        value={value ?? ""}
        onChange={(e) => {
          const emp = list.data?.results.find((x) => x.id === Number(e.target.value));
          if (emp) onChange(emp.id, emp.full_name);
        }}
      >
        <option value="">Escolha um funcionário…</option>
        {list.data?.results.map((e) => (
          <option key={e.id} value={e.id}>
            {e.full_name} ({e.registration})
          </option>
        ))}
      </select>
    </span>
  );
}
