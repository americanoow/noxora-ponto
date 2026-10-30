import { request } from "../http";
import type { Page } from "../operationsApi";
import type { TimeRecord } from "../timeclockApi";

export type AvailabilityStatus =
  "available" | "busy" | "on_break" | "away" | "external" | "unavailable";
export const AVAILABILITY_LABELS: Record<AvailabilityStatus | "unknown", string> = {
  available: "Disponível",
  busy: "Ocupado",
  on_break: "Em pausa",
  away: "Ausente",
  external: "Atividade externa",
  unavailable: "Indisponível",
  unknown: "Sem informação",
};

export interface BoardEmployee {
  employee: { id: number; name: string; registration: string };
  status: AvailabilityStatus | "unknown";
  status_label: string;
  freshness: "confirmed" | "stale" | "expired" | "unknown";
  note: string;
  updated_at: string | null;
  updated_by_source: string | null;
  expires_at: string | null;
  punch_hint: {
    last_punch_at: string;
    unit_name?: string | null;
    likely_present: boolean;
    text: string;
  } | null;
}
export interface BoardGroup {
  unit: { id: number; name: string } | null;
  sector: { id: number; name: string } | null;
  counts: Record<string, number>;
  stale: number;
  employees: BoardEmployee[];
}
export interface Board {
  generated_at: string;
  stale_after_minutes: number;
  notice: string;
  groups: BoardGroup[];
}

const c_ = (c: number) => `/api/companies/${c}`;
export const getBoard = (c: number, unit?: number) =>
  request<Board>("GET", `${c_(c)}/availability/${unit ? `?unit=${unit}` : ""}`);
export const setAvailability = (
  c: number,
  employeeId: number,
  status: AvailabilityStatus,
  note: string,
  expires?: number,
) =>
  request<unknown>("POST", `${c_(c)}/availability/`, {
    employee_id: employeeId,
    status,
    note,
    expires_minutes: expires ?? null,
  });
export const setMyAvailability = (c: number, status: AvailabilityStatus, note = "") =>
  request<unknown>("POST", `${c_(c)}/me/availability/`, { status, note });
export const getMyAvailability = (c: number) =>
  request<{ status: AvailabilityStatus; set_at: string } | null>(
    "GET",
    `${c_(c)}/me/availability/`,
  );

// Portal
export const listMyPunches = (c: number) =>
  request<Page<TimeRecord>>("GET", `${c_(c)}/me/punches/`);
export interface MyClosing {
  id: number;
  start: string;
  end: string;
  status: string;
  acknowledged_at: string | null;
}
export const listMyClosings = (c: number) => request<MyClosing[]>("GET", `${c_(c)}/me/closings/`);
export const acknowledgeClosing = (c: number, id: number, comment: string) =>
  request<unknown>("POST", `${c_(c)}/me/closings/${id}/acknowledge/`, { comment });

// Arquivos e relatórios (downloads diretos com o cookie da sessão)
export const downloads = {
  timesheet: (c: number, employee: number, from: string, to: string, format: "pdf" | "csv") =>
    `${c_(c)}/reports/timesheet/?employee=${employee}&from=${from}&to=${to}&format=${format}`,
  myTimesheet: (c: number, from: string, to: string) =>
    `${c_(c)}/me/timesheet.pdf?from=${from}&to=${to}`,
  myReceipt: (c: number, id: number) => `${c_(c)}/me/punches/${id}/receipt/?format=pdf`,
  receipt: (c: number, id: number) => `${c_(c)}/time-records/${id}/receipt.pdf`,
  summary: (c: number, from: string, to: string) =>
    `${c_(c)}/reports/summary.csv?from=${from}&to=${to}`,
  records: (c: number, from: string, to: string) =>
    `${c_(c)}/reports/time-records.csv?from=${from}&to=${to}`,
  afd: (c: number, unit: number, from: string, to: string) =>
    `${c_(c)}/fiscal/afd/?unit=${unit}&from=${from}&to=${to}`,
  payroll: (c: number, profile: number, closing: number) =>
    `${c_(c)}/fiscal/payroll-export/?profile=${profile}&closing=${closing}`,
};

export interface PayrollProfile {
  id: number;
  name: string;
  file_format: "csv" | "fixed";
  event_codes: Record<string, string>;
  is_active: boolean;
}
export const getPayrollProfiles = (c: number) =>
  request<{ events: Record<string, string>; profiles: PayrollProfile[] }>(
    "GET",
    `${c_(c)}/fiscal/payroll-profiles/`,
  );
export const createPayrollProfile = (
  c: number,
  name: string,
  fileFormat: "csv" | "fixed",
  codes: Record<string, string>,
) =>
  request<PayrollProfile>("POST", `${c_(c)}/fiscal/payroll-profiles/`, {
    name,
    file_format: fileFormat,
    event_codes: codes,
  });
export interface GeneratedFile {
  id: number;
  kind: string;
  unit_id: number | null;
  start: string;
  end: string;
  sha256: string;
  size: number;
  generated_at: string;
  generated_by: string;
  metadata: { pending?: string[] };
}
export const listGeneratedFiles = (c: number) =>
  request<GeneratedFile[]>("GET", `${c_(c)}/fiscal/files/`);

// Cobrança
export interface Plan {
  id: number;
  code: string;
  name: string;
  base_price_cents: number;
  price_per_employee_cents: number;
  max_employees: number | null;
  max_devices: number | null;
  features: string[];
}
export interface Subscription {
  id: number;
  company_id: number;
  plan: Plan;
  status: string;
  status_label: string;
  trial_ends_at: string | null;
  current_period_end: string;
  cancel_at_period_end: boolean;
  sandbox: boolean;
}
export interface Invoice {
  id: number;
  period_start: string;
  period_end: string;
  plan_code: string;
  active_employees: number;
  amount_cents: number;
  status: string;
  due_at: string;
  paid_at: string | null;
}
export interface BillingInfo {
  subscription: Subscription | null;
  usage: { active_employees: number; active_devices: number };
  invoices: Invoice[];
  plans: Plan[];
  notice: string;
}
export const getBilling = (c: number) => request<BillingInfo>("GET", `${c_(c)}/billing/`);
export const changePlan = (c: number, code: string) =>
  request<Subscription>("POST", `${c_(c)}/billing/plan/`, { plan_code: code });
export const setCancel = (c: number, cancel: boolean) =>
  request<Subscription>("POST", `${c_(c)}/billing/cancel/`, { cancel });

// Plataforma
export interface PlatformRow {
  company: { id: number; name: string; is_active: boolean };
  subscription: Subscription | null;
  usage: { active_employees: number; active_devices: number };
  open_invoices: number;
}
export const listPlatformSubscriptions = () =>
  request<PlatformRow[]>("GET", "/api/platform/subscriptions/");
export const listPlatformPlans = () => request<Plan[]>("GET", "/api/platform/plans/");
export const startSubscription = (companyId: number, planCode: string, trialDays: number) =>
  request<Subscription>("POST", `/api/platform/companies/${companyId}/subscription/`, {
    plan_code: planCode,
    trial_days: trialDays,
  });
export const runBilling = () =>
  request<{ invoices_issued: number; subscriptions_suspended: number }>(
    "POST",
    "/api/platform/billing/run/",
  );

// Conta (segundo fator)
export const startMfa = () =>
  request<{ secret: string; otpauth_uri: string }>("POST", "/api/auth/mfa/");
export const confirmMfa = (code: string) =>
  request<{ recovery_codes: string[] }>("PUT", "/api/auth/mfa/", { code });
export const disableMfa = (password: string, code: string) =>
  request<void>("DELETE", "/api/auth/mfa/", { password, code });
