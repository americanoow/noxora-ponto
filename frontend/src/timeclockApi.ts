import { request } from "./http";
import type { Page } from "./operationsApi";

export interface TimeRecord {
  id: number;
  nsr: number;
  unit: { id: number; name: string };
  employee: { id: number; registration: string; name: string };
  device: { id: number; name: string };
  occurred_at: string;
  occurred_offset_minutes: number;
  occurred_local_date: string;
  declared_kind: "" | "entry" | "break_start" | "break_end" | "exit";
  offline: boolean;
  clock_skew_seconds: number | null;
  identification_method: string;
  cpf: string;
  hash_sha256: string;
}

export interface Employer {
  legal_name: string;
  tax_id_type: "" | "CNPJ" | "CPF";
  tax_id: string;
  cei_caepf_cno: string;
}

export interface RecordFilters {
  from: string;
  to: string;
  page: number;
}

const base = (c: number) => `/api/companies/${c}`;

export function listTimeRecords(c: number, f: RecordFilters) {
  const params = new URLSearchParams({ page: String(f.page) });
  if (f.from) params.set("from", f.from);
  if (f.to) params.set("to", f.to);
  return request<Page<TimeRecord>>("GET", `${base(c)}/time-records/?${params}`);
}

export const getEmployer = (c: number) => request<Employer>("GET", `${base(c)}/employer/`);
export const updateEmployer = (c: number, changes: Partial<Employer>) =>
  request<Employer>("PATCH", `${base(c)}/employer/`, changes);

/** Horário local da marcação, no fuso em que foi gravada (não no do navegador). */
export function formatLocalTime(iso: string, offsetMinutes: number): string {
  const local = new Date(new Date(iso).getTime() + offsetMinutes * 60_000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${pad(local.getUTCDate())}/${pad(local.getUTCMonth() + 1)}/${local.getUTCFullYear()} ` +
    `${pad(local.getUTCHours())}:${pad(local.getUTCMinutes())}:${pad(local.getUTCSeconds())}`
  );
}

export const KIND_LABELS: Record<string, string> = {
  "": "—",
  entry: "Entrada",
  break_start: "Início de intervalo",
  break_end: "Fim de intervalo",
  exit: "Saída",
};
