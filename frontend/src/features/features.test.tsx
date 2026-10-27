import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DayResult, Timesheet } from "../api/attendance";
import { App } from "../App";
import { resetCsrf } from "../http";
import { DayRuler } from "../ui/DayRuler";

type Handler = (init?: RequestInit) => { status?: number; body?: unknown };
let routes: Record<string, Handler>;
let calls: { url: string; init?: RequestInit }[];

const admin = {
  id: 1,
  email: "adm@a.test",
  name: "Adm",
  is_platform_admin: false,
  memberships: [{ id: 1, company_id: 7, company_name: "Empresa A", role: "company_admin" }],
};

function day(partial: Partial<DayResult>): DayResult {
  return {
    date: "2026-10-19",
    holiday: "",
    planned: {
      start: "2026-10-19T11:00:00+00:00",
      end: "2026-10-19T20:00:00+00:00",
      start_local: "2026-10-19 08:00",
      end_local: "2026-10-19 17:00",
      break_minutes: 60,
    },
    marks: [],
    ignored_marks: [],
    expected_minutes: 480,
    worked_minutes: 0,
    break_minutes: 0,
    late_minutes: 0,
    early_leave_minutes: 0,
    overtime_minutes: 0,
    overtime_rate_percent: 0,
    deficit_minutes: 0,
    night_minutes: 0,
    night_reduced_minutes: 0,
    break_suppressed_minutes: 0,
    rest_violation_minutes: 0,
    justified_minutes: 0,
    tolerance_applied: false,
    status: "ok",
    issues: [],
    steps: ["Jornada prevista: 19/10 08:00 a 19/10 17:00."],
    ...partial,
  };
}

const mark = (local: string, id: number) => ({
  at: `${local.replace(" ", "T")}:00-03:00`,
  local,
  record_id: id,
  origin: "original" as const,
  flags: [],
});

const sheet: Timesheet = {
  employee: { id: 4, registration: "1003", name: "Diego" },
  timezone: "America/Sao_Paulo",
  period: { from: "2026-10-19", to: "2026-10-19" },
  engine_version: "apuracao-v1",
  rule_versions: [{ from: "2026-10-19", to: "2026-10-19", version: 0 }],
  days: [
    day({
      marks: [
        mark("2026-10-19 08:00", 1),
        mark("2026-10-19 12:00", 2),
        mark("2026-10-19 13:00", 3),
      ],
      status: "inconsistent",
      issues: ["Número ímpar de marcações"],
      worked_minutes: 240,
    }),
  ],
  totals: {
    expected_minutes: 480,
    worked_minutes: 240,
    late_minutes: 0,
    early_leave_minutes: 0,
    deficit_minutes: 0,
    night_minutes: 0,
    night_reduced_minutes: 0,
    break_suppressed_minutes: 0,
    justified_minutes: 0,
    overtime_by_rate: {},
    overtime_minutes: 0,
    balance_minutes: 0,
    days_with_issues: 1,
    absences: 0,
    inconsistent_days: 1,
  },
  pending_requests: 0,
  closings: [],
};

beforeEach(() => {
  calls = [];
  resetCsrf();
  window.location.hash = "";
  routes = {
    "GET /api/auth/csrf/": () => ({ body: { csrfToken: "tok" } }),
    "GET /api/auth/me/": () => ({ body: admin }),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const key = `${init?.method ?? "GET"} ${url.split("?")[0]}`;
      const handler = routes[key];
      const { status = 200, body = [] } = handler ? handler(init) : { status: 404, body: {} };
      return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("Régua do dia", () => {
  it("posiciona marcações e o previsto nas 24 h e descreve as marcações", () => {
    const { container } = render(
      <DayRuler day={day({ marks: [mark("2026-10-19 06:00", 1), mark("2026-10-19 18:00", 2)] })} />,
    );
    const pins = container.querySelectorAll<HTMLElement>(".pin");
    expect([...pins].map((p) => p.style.left)).toEqual(["25%", "75%"]);
    expect(container.querySelector<HTMLElement>(".planned")!.style.left).toBe(`${(8 / 24) * 100}%`);
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", "Marcações: 06:00, 18:00");
  });

  it("turno que cruza a meia-noite usa régua de 30 h e marca período aberto", () => {
    const { container } = render(
      <DayRuler
        day={day({
          marks: [
            mark("2026-10-19 22:00", 1),
            mark("2026-10-20 02:00", 2),
            mark("2026-10-20 03:00", 3),
          ],
        })}
      />,
    );
    const pins = [...container.querySelectorAll<HTMLElement>(".pin")].map((p) =>
      parseFloat(p.style.left),
    );
    expect(pins[1]).toBeCloseTo((26 / 30) * 100);
    expect(container.querySelector(".worked.open")).not.toBeNull();
  });
});

describe("Espelho de ponto", () => {
  it("abre o dia, explica o cálculo e envia pedido de inclusão no fuso da unidade", async () => {
    window.location.hash = "#/timesheet?employeeId=4&from=2026-10-19&to=2026-10-19";
    routes["GET /api/companies/7/attendance/timesheet/"] = () => ({ body: sheet });
    routes["GET /api/companies/7/employees/"] = () => ({
      body: { count: 0, next: null, previous: null, results: [] },
    });
    routes["POST /api/companies/7/attendance/requests/"] = () => ({ status: 201, body: {} });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /seg 19\/10/ }));
    expect(screen.getByText("Como calculamos")).toBeInTheDocument();
    expect(screen.getByText(/Número ímpar/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Pedir ajuste ou abono/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/Horário esquecido/), {
      target: { value: "17:30" },
    });
    fireEvent.change(within(dialog).getByLabelText("Justificativa"), {
      target: { value: "Esqueci a saída" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Enviar pedido" }));
    await waitFor(() =>
      expect(calls.some((c) => c.url.endsWith("/attendance/requests/"))).toBe(true),
    );
    const sent = JSON.parse(
      String(calls.find((c) => c.url.endsWith("/attendance/requests/"))!.init!.body),
    );
    expect(sent).toEqual({
      employee_id: 4,
      kind: "include",
      occurred_at: "2026-10-19T17:30:00-03:00",
      reason: "Esqueci a saída",
    });
  });
});

describe("Pedidos", () => {
  it("recusa exige observação e aprova com um toque", async () => {
    window.location.hash = "#/requests";
    const pending = {
      id: 9,
      type: "justification",
      employee: { id: 4, name: "Diego", registration: "1003" },
      kind: "medical",
      kind_label: "Atestado médico",
      reason: "Consulta",
      status: "pending",
      requested_by: { id: 2, email: "g@a.test" },
      requested_at: "2026-10-20T12:00:00Z",
      decided_by: null,
      decided_at: null,
      decision_note: "",
      date: "2026-10-19",
      minutes: null,
      document_ref: "",
    };
    routes["GET /api/companies/7/attendance/requests/"] = () => ({ body: [pending] });
    routes["POST /api/companies/7/attendance/justifications/9/decision/"] = (init) => {
      const body = JSON.parse(String(init!.body));
      return body.approve || body.note
        ? { body: { ...pending, status: body.approve ? "approved" : "rejected" } }
        : { status: 400, body: { note: ["Informe o motivo da recusa."] } };
    };
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Decidir" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Recusar" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Informe o motivo da recusa.",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Aprovar" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("Login com segundo fator", () => {
  it("pede o código e só então abre o painel", async () => {
    routes["GET /api/auth/me/"] = () => ({ status: 403 });
    routes["POST /api/auth/login/"] = () => ({ body: { mfa_required: true } });
    routes["POST /api/auth/mfa/verify/"] = () => ({ body: admin });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("E-mail"), { target: { value: "adm@a.test" } });
    fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "senha-longa-123" } });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));
    fireEvent.change(await screen.findByLabelText(/Código do aplicativo/), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    expect(await screen.findByRole("navigation", { name: "Jornada" })).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/auth/mfa/verify/")).toBe(true);
  });
});
