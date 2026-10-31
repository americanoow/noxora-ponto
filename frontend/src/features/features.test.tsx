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
    timezone: "America/Sao_Paulo",
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
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", "Registros: 06:00, 18:00");
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
    // O último registro não tem par: vira pendência e nenhum período é inventado para ele.
    expect(container.querySelector(".pin.pending")).not.toBeNull();
    expect(container.querySelectorAll(".worked")).toHaveLength(1);
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
    expect(screen.getByText(/Como chegamos a esse número/)).toBeInTheDocument();
    expect(screen.getByText(/Número ímpar/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Pedir ajuste/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/Que horas você deveria ter batido/), {
      target: { value: "17:30" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Explique o motivo/), {
      target: { value: "Esqueci a saída" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Enviar solicitação" }));
    await waitFor(() =>
      expect(calls.some((c) => c.url.endsWith("/attendance/requests/"))).toBe(true),
    );
    const sent = JSON.parse(
      String(calls.find((c) => c.url.endsWith("/attendance/requests/"))!.init!.body),
    );
    expect(sent).toEqual({
      employee_id: 4,
      kind: "include",
      occurred_local: "2026-10-19T17:30",
      reason: "Esqueci a saída",
    });
  });

  it("turno noturno: permite pedir a batida na madrugada do dia seguinte, sem fuso do navegador", async () => {
    window.location.hash = "#/timesheet?employeeId=4&from=2026-10-19&to=2026-10-19";
    routes["GET /api/companies/7/attendance/timesheet/"] = () => ({ body: sheet });
    routes["GET /api/companies/7/employees/"] = () => ({
      body: { count: 0, next: null, previous: null, results: [] },
    });
    routes["POST /api/companies/7/attendance/requests/"] = () => ({ status: 201, body: {} });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /seg 19\/10/ }));
    fireEvent.click(screen.getByRole("button", { name: /Pedir ajuste/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/Que horas você deveria ter batido/), {
      target: { value: "07:00" },
    });
    fireEvent.click(within(dialog).getByLabelText(/madrugada do dia seguinte/));
    expect(within(dialog).getByText(/20\/10\/2026 às 07:00/)).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText(/Explique o motivo/), {
      target: { value: "Esqueci a saída" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Enviar solicitação" }));
    await waitFor(() =>
      expect(calls.some((c) => c.url.endsWith("/attendance/requests/"))).toBe(true),
    );
    const sent = JSON.parse(
      String(calls.find((c) => c.url.endsWith("/attendance/requests/"))!.init!.body),
    );
    expect(sent.occurred_local).toBe("2026-10-20T07:00");
    expect(sent.occurred_at).toBeUndefined();
  });
});

describe("Solicitações", () => {
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
    routes["GET /api/companies/7/attendance/requests/"] = () => ({
      body: { count: 1, next: null, previous: null, results: [pending] },
    });
    routes["POST /api/companies/7/attendance/justifications/9/decision/"] = (init) => {
      const body = JSON.parse(String(init!.body));
      return body.approve || body.note
        ? { body: { ...pending, status: body.approve ? "approved" : "rejected" } }
        : { status: 400, body: { note: ["Informe o motivo da recusa."] } };
    };
    render(<App />);
    expect(await screen.findByText("Original e solicitado")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Recusar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Informe o motivo da recusa.");
    fireEvent.click(screen.getByRole("button", { name: "Aprovar" }));
    await waitFor(() =>
      expect(calls.filter((c) => c.url.endsWith("/justifications/9/decision/"))).toHaveLength(2),
    );
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
    fireEvent.change(await screen.findByLabelText(/Código de 6 dígitos/), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    expect(await screen.findByRole("navigation", { name: "Menu principal" })).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/auth/mfa/verify/")).toBe(true);
  });
});

const page = <T,>(results: T[], count = results.length) => ({
  body: { count, next: null, previous: null, results },
});

describe("Fechamento com exceção", () => {
  it("só pede o motivo depois que o servidor recusa por registro incompleto e envia a exceção", async () => {
    window.location.hash = "#/closings";
    routes["GET /api/companies/7/attendance/closings/"] = () => page([]);
    routes["GET /api/companies/7/attendance/requests/"] = () => page([], 0);
    routes["GET /api/companies/7/devices/"] = () => ({ body: [] });
    routes["GET /api/companies/7/attendance/summary/"] = () => page([]);
    let attempt = 0;
    routes["POST /api/companies/7/attendance/closings/"] = () => {
      attempt += 1;
      return attempt === 1
        ? {
            status: 400,
            body: { detail: "Há 1 dia(s) com registro incompleto.", code: "incomplete_marks" },
          }
        : { status: 201, body: { id: 5 } };
    };
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Fechar o mês" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continuar" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continuar" }));
    fireEvent.click(await screen.findByLabelText(/Revisei as pendências/));
    expect(screen.queryByLabelText(/Motivo da exceção/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Fechar período" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/registro incompleto/);
    const reason = await screen.findByLabelText(/Motivo da exceção/);
    const button = screen.getByRole("button", { name: "Fechar com exceção" });
    expect(button).toBeDisabled();
    fireEvent.change(reason, { target: { value: "Funcionário em férias coletivas" } });
    fireEvent.click(button);
    await waitFor(() => expect(attempt).toBe(2));
    const posts = calls.filter((c) => c.init?.method === "POST");
    expect(JSON.parse(String(posts[1].init!.body))).toMatchObject({
      accept_incomplete: true,
      exception_reason: "Funcionário em férias coletivas",
    });
    expect(JSON.parse(String(posts[0].init!.body)).accept_incomplete).toBeUndefined();
  });
});

describe("Banco de horas", () => {
  const bank = {
    employee: { id: 4, registration: "1003", name: "Diego" },
    ledger_minutes: 120,
    accrued_closed_minutes: 30,
    balance_minutes: 150,
    opening_date: "2026-09-01",
    closed_periods: [],
    notice: "Regras de compensação dependem de acordo ou convenção coletiva.",
    entries: [
      {
        id: 1,
        kind: "opening",
        kind_label: "Saldo inicial",
        date: "2026-09-01",
        minutes: 120,
        reason: "Saldo migrado",
        created_by: "adm@a.test",
        created_at: "2026-09-01T10:00:00Z",
        reverses: null,
        reversed: false,
      },
    ],
  };

  it("mostra o banco separado do saldo do período e lança abatimento com sinal negativo", async () => {
    window.location.hash = "#/timesheet?employeeId=4&from=2026-10-19&to=2026-10-19";
    routes["GET /api/companies/7/attendance/timesheet/"] = () => ({ body: sheet });
    routes["GET /api/companies/7/employees/"] = () => page([], 0);
    routes["GET /api/companies/7/attendance/employees/4/hour-bank/"] = () => ({ body: bank });
    routes["POST /api/companies/7/attendance/employees/4/hour-bank/"] = () => ({
      status: 201,
      body: bank,
    });
    render(<App />);
    expect(await screen.findByText("Saldo do período")).toBeInTheDocument();
    expect(await screen.findByText("Saldo do banco")).toBeInTheDocument();
    expect(screen.getByText("+02:30")).toBeInTheDocument();
    expect(screen.getByText(/convenção coletiva/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Novo lançamento" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/^Tipo/), { target: { value: "offset" } });
    fireEvent.change(within(dialog).getByLabelText(/^Horas/), { target: { value: "2" } });
    fireEvent.change(within(dialog).getByLabelText(/^Motivo/), {
      target: { value: "Folga compensada" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Lançar" }));
    await waitFor(() =>
      expect(
        calls.some((c) => c.url.endsWith("/employees/4/hour-bank/") && c.init?.method === "POST"),
      ).toBe(true),
    );
    const sent = JSON.parse(
      String(
        calls.find((c) => c.url.endsWith("/employees/4/hour-bank/") && c.init?.method === "POST")!
          .init!.body,
      ),
    );
    expect(sent).toMatchObject({ kind: "offset", minutes: -120, reason: "Folga compensada" });
  });
});

describe("Conta: operações sensíveis", () => {
  it("pede a senha de novo quando o servidor exige login recente e repete a ação", async () => {
    window.location.hash = "#/account";
    let starts = 0;
    routes["POST /api/auth/mfa/"] = () => {
      starts += 1;
      return starts === 1
        ? { status: 403, body: { detail: "confirme", code: "reauth_required" } }
        : { body: { secret: "ABCDEFGHIJKLMNOP", otpauth_uri: "otpauth://totp/x" } };
    };
    routes["POST /api/auth/reauth/"] = () => ({ status: 204, body: {} });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Começar a configurar" }));
    fireEvent.change(await screen.findByLabelText("Senha"), {
      target: { value: "senha-longa-123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar senha" }));
    expect(await screen.findByText(/Chave para digitar no aplicativo/)).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/auth/reauth/")).toBe(true);
    expect(starts).toBe(2);
  });
});

describe("Portal do funcionário", () => {
  it("Minha folha reúne os meses fechados e registra a ciência no mesmo lugar", async () => {
    window.location.hash = "#/my-timesheet";
    routes["GET /api/auth/me/"] = () => ({
      body: {
        ...admin,
        memberships: [{ id: 1, company_id: 7, company_name: "Empresa A", role: "employee" }],
      },
    });
    routes["GET /api/companies/7/me/timesheet/"] = () => ({ body: sheet });
    routes["GET /api/companies/7/me/hour-bank/"] = () => ({ status: 404, body: {} });
    routes["GET /api/companies/7/me/closings/"] = () => ({
      body: [
        { id: 3, start: "2026-09-01", end: "2026-09-30", status: "closed", acknowledged_at: null },
      ],
    });
    routes["POST /api/companies/7/me/closings/3/acknowledge/"] = () => ({ body: {} });
    render(<App />);
    expect(await screen.findByText("Meses fechados")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Registrar ciência" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Registrar ciência" }));
    await waitFor(() =>
      expect(calls.some((c) => c.url.endsWith("/me/closings/3/acknowledge/"))).toBe(true),
    );
    // Não existe mais uma tela separada de meses fechados no menu.
    expect(
      within(screen.getByLabelText("Menu principal")).queryByRole("button", {
        name: "Meses fechados",
      }),
    ).not.toBeInTheDocument();
  });
});

describe("Lista de funcionários e acesso", () => {
  const employee = (id: number, name: string) => ({
    id,
    registration: String(id),
    full_name: name,
    cpf: "***.***.***-25",
    is_active: true,
    unit: { id: 1, name: "Centro" },
    sector: null,
  });

  it("lista com CPF protegido, busca com filtro e paginação só quando há mais páginas", async () => {
    window.location.hash = "#/employees";
    routes["GET /api/companies/7/employees/"] = () => ({
      body: { count: 40, next: "x", previous: null, results: [employee(1, "Ana")] },
    });
    routes["GET /api/companies/7/units/"] = () => ({ body: [] });
    render(<App />);
    expect(await screen.findByText("Ana")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Buscar/), { target: { value: "ana" } });
    await waitFor(() => expect(calls.some((c) => c.url.includes("q=ana"))).toBe(true));
    fireEvent.click(await screen.findByRole("button", { name: "Próxima" }));
    await waitFor(() => expect(calls.some((c) => c.url.includes("page=2"))).toBe(true));
  });

  it("convida e dá acesso em um passo, sem mandar o gestor para outra tela", async () => {
    window.location.hash = "#/employee?id=5";
    routes["GET /api/companies/7/employees/5/"] = () => ({
      body: { ...employee(5, "Bia"), admission_date: null, access_email: "", cpf: "***" },
    });
    routes["GET /api/companies/7/employees/5/assignments/"] = () => ({ body: [] });
    routes["GET /api/companies/7/employees/5/schedules/"] = () => ({ body: [] });
    routes["POST /api/companies/7/employees/5/access/"] = () => ({ status: 201, body: {} });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    const dialog = await screen.findByRole("dialog");
    const email = within(dialog).getByLabelText(/E-mail para acessar o sistema/);
    const invite = within(dialog).getByRole("button", { name: "Convidar e dar acesso" });
    expect(invite).toBeDisabled();
    fireEvent.change(email, { target: { value: "bia@a.test" } });
    fireEvent.click(invite);
    await waitFor(() =>
      expect(calls.some((c) => c.url.endsWith("/employees/5/access/"))).toBe(true),
    );
    const sent = JSON.parse(
      String(calls.find((c) => c.url.endsWith("/employees/5/access/"))!.init!.body),
    );
    expect(sent).toEqual({ email: "bia@a.test" });
  });
});

describe("Abas que levam o contexto", () => {
  it("o período escolhido na folha vai e volta com as abas", async () => {
    window.location.hash = "#/timesheet?employeeId=4&from=2026-09-01&to=2026-09-30";
    routes["GET /api/companies/7/attendance/timesheet/"] = () => ({ body: sheet });
    routes["GET /api/companies/7/employees/"] = () => page([], 0);
    routes["GET /api/companies/7/time-records/"] = () => page([], 0);
    render(<App />);
    const tabs = within(await screen.findByRole("group", { name: "Partes desta seção" }));
    fireEvent.click(tabs.getByRole("button", { name: "Registros originais" }));
    expect(await screen.findByLabelText("De")).toHaveValue("2026-09-01");
    expect(screen.getByLabelText("Até")).toHaveValue("2026-09-30");
    expect(window.location.hash).toContain("from=2026-09-01");
    expect(screen.getByRole("link", { name: /Planilha das batidas/ })).toHaveAttribute(
      "href",
      expect.stringContaining("from=2026-09-01&to=2026-09-30"),
    );
    fireEvent.click(
      within(screen.getByRole("group", { name: "Partes desta seção" })).getByRole("button", {
        name: "Folha de ponto",
      }),
    );
    await waitFor(() => expect(window.location.hash).toContain("employeeId=4"));
    expect(window.location.hash).toContain("from=2026-09-01");
    expect(window.location.hash).toContain("to=2026-09-30");
  });
});

describe("Privacidade e configurações da empresa", () => {
  it("funcionário vê a situação da biometria, retira a autorização e baixa os próprios dados", async () => {
    window.location.hash = "#/my-timesheet";
    routes["GET /api/auth/me/"] = () => ({
      body: {
        ...admin,
        memberships: [{ id: 1, company_id: 7, company_name: "Empresa A", role: "employee" }],
      },
    });
    routes["GET /api/companies/7/me/timesheet/"] = () => ({ body: sheet });
    routes["GET /api/companies/7/me/closings/"] = () => ({ body: [] });
    let enrolled = true;
    routes["GET /api/companies/7/me/biometric/"] = () => ({
      body: {
        consent: enrolled ? { policy_version: "v1", granted_at: "2026-10-01T10:00:00Z" } : null,
        enrolled,
        enrolled_at: enrolled ? "2026-10-01T10:00:00Z" : null,
        notice: "A biometria é opcional.",
      },
    });
    routes["DELETE /api/companies/7/me/biometric/"] = () => {
      enrolled = false;
      return { body: {} };
    };
    vi.stubGlobal("confirm", () => true);
    render(<App />);
    expect(await screen.findByText(/cadastrado em/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Baixar meus dados" })).toHaveAttribute(
      "href",
      "/api/companies/7/me/data.json",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retirar minha autorização da biometria" }));
    expect(
      await screen.findByText(/não usado \(o ponto é registrado pela matrícula\)/),
    ).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/me/biometric/") && c.init?.method === "DELETE")).toBe(
      true,
    );
  });

  it("a política de marcação sem internet fica só na tela da empresa (sem controle duplicado)", async () => {
    window.location.hash = "#/company";
    routes["GET /api/companies/7/identification/"] = () => ({
      body: {
        mode: "registration",
        offline_policy: "disabled",
        face_liveness_policy: "certified",
        engine: null,
      },
    });
    routes["PATCH /api/companies/7/identification/"] = () => ({
      body: {
        mode: "registration",
        offline_policy: "registration_only",
        face_liveness_policy: "certified",
      },
    });
    routes["GET /api/companies/7/employer/"] = () => ({
      body: { legal_name: "", tax_id_type: "", tax_id: "", cei_caepf_cno: "" },
    });
    render(<App />);
    const selects = await screen.findAllByLabelText(
      /Tablet sem internet|Bater o ponto sem internet/,
    );
    expect(selects).toHaveLength(1);
    fireEvent.change(selects[0], { target: { value: "registration_only" } });
    await waitFor(() =>
      expect(
        calls.some((c) => c.url.endsWith("/identification/") && c.init?.method === "PATCH"),
      ).toBe(true),
    );
  });
});
