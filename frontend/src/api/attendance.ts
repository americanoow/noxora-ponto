import { request } from "../http";
import type { Page } from "../operationsApi";

export interface Mark {
  at: string;
  local: string;
  record_id: number | null;
  origin: "original" | "included";
  flags: string[];
}

export type DayStatus =
  "ok" | "inconsistent" | "absent" | "day_off" | "justified" | "upcoming" | "in_progress";

export interface DayResult {
  date: string;
  holiday: string;
  planned: {
    start: string;
    end: string;
    start_local: string;
    end_local: string;
    break_minutes: number;
  } | null;
  marks: Mark[];
  ignored_marks: Mark[];
  expected_minutes: number;
  worked_minutes: number;
  break_minutes: number;
  late_minutes: number;
  early_leave_minutes: number;
  overtime_minutes: number;
  overtime_rate_percent: number;
  deficit_minutes: number;
  night_minutes: number;
  night_reduced_minutes: number;
  break_suppressed_minutes: number;
  rest_violation_minutes: number;
  justified_minutes: number;
  tolerance_applied: boolean;
  status: DayStatus;
  /** Fuso da unidade em que o dia foi apurado (a lotação vigente naquela data). */
  timezone: string;
  issues: string[];
  steps: string[];
}

export interface Totals {
  expected_minutes: number;
  worked_minutes: number;
  late_minutes: number;
  early_leave_minutes: number;
  deficit_minutes: number;
  night_minutes: number;
  night_reduced_minutes: number;
  break_suppressed_minutes: number;
  justified_minutes: number;
  overtime_by_rate: Record<string, number>;
  overtime_minutes: number;
  balance_minutes: number;
  days_with_issues: number;
  absences: number;
  inconsistent_days: number;
}

export interface ClosingSummary {
  id: number;
  start: string;
  end: string;
  status: "closed" | "reopened";
  snapshot_sha256: string;
  engine_version: string;
  employees: number;
  closed_by: { id: number; email: string } | null;
  closed_at: string;
  /** Exceção autorizada para fechar com registros incompletos, quando houve. */
  exceptions?: {
    kind: string;
    reason: string;
    authorized_by: { id: number; email: string };
    authorized_at: string;
    employees: { id: number; name: string; registration: string; dates: string[] }[];
  } | null;
  reopened_by: { id: number; email: string } | null;
  reopened_at: string | null;
  reopen_reason: string;
  divergent?: boolean;
}

export interface Timesheet {
  employee: { id: number; registration: string; name: string };
  timezone: string;
  period: { from: string; to: string };
  engine_version: string;
  rule_versions: { from: string; to: string; version: number }[];
  days: DayResult[];
  totals: Totals;
  pending_requests: number;
  closings: ClosingSummary[];
}

export type RequestStatus = "pending" | "approved" | "rejected" | "cancelled";

interface RequestBase {
  id: number;
  employee: { id: number; name: string; registration: string };
  kind: string;
  kind_label: string;
  reason: string;
  status: RequestStatus;
  requested_by: { id: number; email: string } | null;
  requested_at: string;
  decided_by: { id: number; email: string } | null;
  decided_at: string | null;
  decision_note: string;
}
export interface AdjustmentRequest extends RequestBase {
  type: "adjustment";
  record_id: number | null;
  record_occurred_at: string | null;
  occurred_at: string | null;
  reference_date: string;
}
export interface JustificationRequest extends RequestBase {
  type: "justification";
  date: string;
  minutes: number | null;
  document_ref: string;
}
export type AttendanceRequest = AdjustmentRequest | JustificationRequest;

export type NewRequest =
  | { type?: "adjustment"; kind: "include"; occurred_local: string; reason: string }
  | { type?: "adjustment"; kind: "disregard"; record_id: number; reason: string }
  | {
      type: "justification";
      date: string;
      kind: string;
      minutes?: number | null;
      reason: string;
      document_ref?: string;
    };

export const JUSTIFICATION_KINDS: [string, string][] = [
  ["medical", "Atestado médico"],
  ["justified_absence", "Falta com justificativa"],
  ["external_work", "Trabalho externo"],
  ["compensation", "Compensação de horas"],
  ["other", "Outro"],
];

export interface SummaryRow {
  employee: { id: number; registration: string; name: string };
  totals: Totals;
  pending_requests: number;
}

export interface RuleSet {
  id: number;
  version: number;
  valid_from: string;
  params: Record<string, unknown>;
  note: string;
  created_by: { email: string } | null;
  created_at: string;
}
export interface RulesInfo {
  defaults: Record<string, unknown>;
  references: Record<string, string>;
  engine_version: string;
  notice: string;
  versions: RuleSet[];
}
export interface Holiday {
  id: number;
  date: string;
  name: string;
  unit_id: number | null;
}
export interface Acknowledgement {
  employee: { id: number; name: string; registration: string };
  acknowledged_at: string | null;
  comment: string;
  matches_snapshot: boolean | null;
}

const base = (c: number) => `/api/companies/${c}/attendance`;
const q = (params: Record<string, string | number | undefined>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") p.set(k, String(v));
  return p.toString();
};

export const getTimesheet = (c: number, employee: number, from: string, to: string) =>
  request<Timesheet>("GET", `${base(c)}/timesheet/?${q({ employee, from, to })}`);
export const getSummary = (c: number, from: string, to: string, unit?: number, page = 1) =>
  request<Page<SummaryRow>>("GET", `${base(c)}/summary/?${q({ from, to, unit, page })}`);
export interface RequestQuery {
  status?: RequestStatus;
  employee?: number;
  /** Datas de referência dos pedidos (AAAA-MM-DD). */
  from?: string;
  to?: string;
  page?: number;
  pageSize?: number;
}
/** Pedidos paginados: `count` é o total real; nada some em silêncio. */
export const listRequests = (c: number, query: RequestQuery = {}) =>
  request<Page<AttendanceRequest>>(
    "GET",
    `${base(c)}/requests/?${q({
      status: query.status,
      employee: query.employee,
      from: query.from,
      to: query.to,
      page: query.page,
      page_size: query.pageSize ?? 50,
    })}`,
  );
export const countRequests = async (c: number, query: RequestQuery = {}) =>
  (await listRequests(c, { ...query, pageSize: 1 })).count;
export const createRequest = (c: number, employeeId: number, body: NewRequest) =>
  request<AttendanceRequest>("POST", `${base(c)}/requests/`, { employee_id: employeeId, ...body });
export const decideRequest = (c: number, item: AttendanceRequest, approve: boolean, note = "") =>
  request<AttendanceRequest>(
    "POST",
    `${base(c)}/${item.type === "adjustment" ? "adjustments" : "justifications"}/${item.id}/decision/`,
    { approve, note },
  );
export const listClosings = (c: number, page = 1) =>
  request<Page<ClosingSummary>>("GET", `${base(c)}/closings/?${q({ page })}`);
export const getClosing = (c: number, id: number) =>
  request<
    ClosingSummary & {
      snapshot: { employees: { employee: Timesheet["employee"]; totals: Totals }[] };
    }
  >("GET", `${base(c)}/closings/${id}/`);
/** `exceptionReason`: autoriza fechar com registros incompletos (mínimo de 10 caracteres, fica auditado). */
export const closePeriod = (c: number, start: string, end: string, exceptionReason?: string) =>
  request<ClosingSummary>("POST", `${base(c)}/closings/`, {
    start,
    end,
    ...(exceptionReason ? { accept_incomplete: true, exception_reason: exceptionReason } : {}),
  });

// Banco de horas: livro-razão separado da apuração (lançamentos imutáveis; erro se corrige por estorno).
export type HourBankKind = "opening" | "offset" | "payout" | "adjustment" | "reversal";
export interface HourBank {
  employee: { id: number; registration: string; name: string };
  ledger_minutes: number;
  accrued_closed_minutes: number;
  balance_minutes: number;
  opening_date: string | null;
  closed_periods: { start: string; end: string; balance_minutes: number }[];
  notice: string;
  entries: {
    id: number;
    kind: HourBankKind;
    kind_label: string;
    date: string;
    minutes: number;
    reason: string;
    created_by: string;
    created_at: string;
    reverses: number | null;
    reversed: boolean;
  }[];
}
export const getHourBank = (c: number, employeeId: number) =>
  request<HourBank>("GET", `${base(c)}/employees/${employeeId}/hour-bank/`);
export const getMyHourBank = (c: number) =>
  request<HourBank>("GET", `/api/companies/${c}/me/hour-bank/`);
export const addHourBankEntry = (
  c: number,
  employeeId: number,
  body: { kind: Exclude<HourBankKind, "reversal">; date: string; minutes: number; reason: string },
) => request<HourBank>("POST", `${base(c)}/employees/${employeeId}/hour-bank/`, body);
export const reverseHourBankEntry = (
  c: number,
  employeeId: number,
  entryId: number,
  reason: string,
) =>
  request<HourBank>("POST", `${base(c)}/employees/${employeeId}/hour-bank/${entryId}/reverse/`, {
    reason,
  });
export const reopenPeriod = (c: number, id: number, reason: string) =>
  request<ClosingSummary>("POST", `${base(c)}/closings/${id}/reopen/`, { reason });
export const listAcknowledgements = (c: number, id: number) =>
  request<Acknowledgement[]>("GET", `${base(c)}/closings/${id}/acknowledgements/`);
export const getRules = (c: number) => request<RulesInfo>("GET", `${base(c)}/rules/`);
export const createRules = (
  c: number,
  validFrom: string,
  params: Record<string, unknown>,
  note: string,
) => request<RuleSet>("POST", `${base(c)}/rules/`, { valid_from: validFrom, params, note });
export const listHolidays = (c: number, year?: number) =>
  request<Holiday[]>("GET", `${base(c)}/holidays/?${q({ year })}`);
export const createHoliday = (c: number, date: string, name: string, unitId: number | null) =>
  request<Holiday>("POST", `${base(c)}/holidays/`, { date, name, unit_id: unitId });
export const deleteHoliday = (c: number, id: number) =>
  request<void>("DELETE", `${base(c)}/holidays/${id}/`);

// Portal do funcionário
const me = (c: number) => `/api/companies/${c}/me`;
export const getMyTimesheet = (c: number, from: string, to: string) =>
  request<Timesheet>("GET", `${me(c)}/timesheet/?${q({ from, to })}`);
export const listMyRequests = (c: number, page = 1) =>
  request<Page<AttendanceRequest>>("GET", `${me(c)}/requests/?${q({ page, page_size: 50 })}`);
export const createMyRequest = (c: number, body: NewRequest) =>
  request<AttendanceRequest>("POST", `${me(c)}/requests/`, body);
export const cancelMyRequest = (c: number, item: AttendanceRequest) =>
  request<{ status: string }>(
    "POST",
    `${me(c)}/${item.type === "adjustment" ? "adjustments" : "justifications"}/${item.id}/cancel/`,
  );
