import { request } from "./http";

export interface Unit {
  id: number;
  name: string;
  timezone: string;
  is_active: boolean;
}
export interface Sector {
  id: number;
  name: string;
  unit: number;
  is_active: boolean;
}
export interface Employee {
  id: number;
  registration: string;
  full_name: string;
  cpf: string;
  is_active: boolean;
  unit: { id: number; name: string } | null;
  sector: { id: number; name: string } | null;
}
export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
export interface ScheduleDay {
  weekday: number;
  start_time: string;
  end_time: string;
  break_minutes: number;
}
export interface Schedule {
  id: number;
  name: string;
  is_active: boolean;
  days: ScheduleDay[];
}
export interface ImportResult {
  total: number;
  valid: number;
  committed: number;
  errors: { line: number; field: string; message: string }[];
}
export interface EmployeeFilters {
  q: string;
  unit: string;
  active: string;
  page: number;
}

const base = (companyId: number) => `/api/companies/${companyId}`;

export const listUnits = (c: number) => request<Unit[]>("GET", `${base(c)}/units/`);
export const createUnit = (c: number, name: string) =>
  request<Unit>("POST", `${base(c)}/units/`, { name });
export const updateUnit = (c: number, id: number, changes: Partial<Unit>) =>
  request<Unit>("PATCH", `${base(c)}/units/${id}/`, changes);

export const listSectors = (c: number) => request<Sector[]>("GET", `${base(c)}/sectors/`);
export const createSector = (c: number, name: string, unit: number) =>
  request<Sector>("POST", `${base(c)}/sectors/`, { name, unit });
export const updateSector = (c: number, id: number, changes: Partial<Sector>) =>
  request<Sector>("PATCH", `${base(c)}/sectors/${id}/`, changes);

export function listEmployees(c: number, f: EmployeeFilters) {
  const params = new URLSearchParams({ page: String(f.page) });
  if (f.q) params.set("q", f.q);
  if (f.unit) params.set("unit", f.unit);
  if (f.active) params.set("active", f.active);
  return request<Page<Employee>>("GET", `${base(c)}/employees/?${params}`);
}
export const createEmployee = (c: number, registration: string, full_name: string, cpf: string) =>
  request<Employee>("POST", `${base(c)}/employees/`, { registration, full_name, cpf });
export const updateEmployee = (c: number, id: number, changes: { is_active?: boolean }) =>
  request<Employee>("PATCH", `${base(c)}/employees/${id}/`, changes);
export const changeAssignment = (
  c: number,
  id: number,
  unit: number,
  sector: number | null,
  validFrom: string,
) =>
  request<unknown>("POST", `${base(c)}/employees/${id}/assignments/`, {
    unit,
    sector,
    valid_from: validFrom,
  });

export const listSchedules = (c: number) => request<Schedule[]>("GET", `${base(c)}/schedules/`);
export const createSchedule = (c: number, name: string, days: ScheduleDay[]) =>
  request<Schedule>("POST", `${base(c)}/schedules/`, { name, days });

export const importEmployees = (c: number, csv: string, commit: boolean) =>
  request<ImportResult>("POST", `${base(c)}/employees/import/`, { csv, commit });
