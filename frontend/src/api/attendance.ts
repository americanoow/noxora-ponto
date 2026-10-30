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
  | { type?: "adjustment"; kind: "include"; occurred_at: string; reason: string }
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
export const listRequests = (c: number, status?: RequestStatus, employee?: number) =>
  request<AttendanceRequest[]>("GET", `${base(c)}/requests/?${q({ status, employee })}`);
export const createRequest = (c: number, employeeId: number, body: NewRequest) =>
  request<AttendanceRequest>("POST", `${base(c)}/requests/`, { employee_id: employeeId, ...body });
export const decideRequest = (c: number, item: AttendanceRequest, approve: boolean, note = "") =>
  request<AttendanceRequest>(
    "POST",
    `${base(c)}/${item.type === "adjustment" ? "adjustments" : "justifications"}/${item.id}/decision/`,
    { approve, note },
  );
export const listClosings = (c: number) => request<ClosingSummary[]>("GET", `${base(c)}/closings/`);
export const getClosing = (c: number, id: number) =>
  request<
    ClosingSummary & {
      snapshot: { employees: { employee: Timesheet["employee"]; totals: Totals }[] };
    }
  >("GET", `${base(c)}/closings/${id}/`);
export const closePeriod = (c: number, start: string, end: string) =>
  request<ClosingSummary>("POST", `${base(c)}/closings/`, { start, end });
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
export const listMyRequests = (c: number) =>
  request<AttendanceRequest[]>("GET", `${me(c)}/requests/`);
export const createMyRequest = (c: number, body: NewRequest) =>
  request<AttendanceRequest>("POST", `${me(c)}/requests/`, body);
export const cancelMyRequest = (c: number, item: AttendanceRequest) =>
  request<{ status: string }>(
    "POST",
    `${me(c)}/${item.type === "adjustment" ? "adjustments" : "justifications"}/${item.id}/cancel/`,
  );
