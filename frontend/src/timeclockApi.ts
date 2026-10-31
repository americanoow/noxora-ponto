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
  sync_flags: string[];
}

export interface Employer {
  legal_name: string;
  tax_id_type: "" | "CNPJ" | "CPF";
  tax_id: string;
  cei_caepf_cno: string;
}

/** Origem da marcação: "" = todas, "false" = online, "true" = offline (sincronizada depois). */
export interface RecordFilters {
  from: string;
  to: string;
  offline: "" | "true" | "false";
  page: number;
}

const base = (c: number) => `/api/companies/${c}`;

export function listTimeRecords(c: number, f: RecordFilters) {
  const params = new URLSearchParams({ page: String(f.page) });
  if (f.from) params.set("from", f.from);
  if (f.to) params.set("to", f.to);
  if (f.offline) params.set("offline", f.offline);
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

/** Sinalizações de revisão gravadas na sincronização de marcações offline (ver apps/timeclock/services.py). */
export const SYNC_FLAG_LABELS: Record<string, string> = {
  clock_unverified: "não foi possível conferir se o relógio do tablet estava certo",
  clock_skew_large: "relógio do tablet estava errado por mais de 30 segundos",
  clock_offset_stale: "o relógio do tablet não era conferido havia muito tempo",
  time_in_future: "horário no futuro; foi usado o horário em que o sistema recebeu",
  before_device_activation: "horário anterior à ativação do tablet",
  employee_inactive: "funcionário estava inativo quando a batida chegou",
  not_assigned_to_unit: "funcionário não trabalhava nesta unidade na data",
  face_fallback_engine_unavailable: "registrada pela matrícula: reconhecimento facial fora do ar",
};

export const KIND_LABELS: Record<string, string> = {
  "": "—",
  entry: "Entrada",
  break_start: "Saída para o intervalo",
  break_end: "Volta do intervalo",
  exit: "Saída",
};
