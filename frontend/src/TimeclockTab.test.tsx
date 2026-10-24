import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetCsrf } from "./http";
import { EmployerTab, RecordsTab } from "./TimeclockTab";
import { formatLocalTime } from "./timeclockApi";

let routes: Record<string, (init?: RequestInit) => { status?: number; body?: unknown }>;
let calls: { key: string; init?: RequestInit }[];

const record = (over = {}) => ({
  id: 1,
  nsr: 42,
  unit: { id: 1, name: "Centro" },
  employee: { id: 5, registration: "100", name: "Ana" },
  device: { id: 2, name: "Tablet 1" },
  occurred_at: "2026-10-22T02:30:15Z",
  occurred_offset_minutes: -180,
  occurred_local_date: "2026-10-21",
  declared_kind: "entry",
  offline: false,
  clock_skew_seconds: null,
  identification_method: "registration",
  cpf: "***.***.***-25",
  hash_sha256: "a".repeat(64),
  ...over,
});

beforeEach(() => {
  calls = [];
  resetCsrf();
  routes = {
    "GET /api/auth/csrf/": () => ({ body: { csrfToken: "tok" } }),
    "GET /api/companies/7/identification/": () => ({ body: { mode: "registration" } }),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url.split("?")[0]}`;
      calls.push({ key: `${init?.method ?? "GET"} ${url}`, init });
      const handler = routes[key];
      const { status = 200, body = {} } = handler ? handler(init) : { status: 404 };
      return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("formatLocalTime", () => {
  it("mostra o horário no fuso gravado, não no do navegador", () => {
    expect(formatLocalTime("2026-10-22T02:30:15Z", -180)).toBe("21/10/2026 23:30:15");
    expect(formatLocalTime("2026-10-21T23:59:59Z", 330)).toBe("22/10/2026 05:29:59");
  });
});

describe("RecordsTab", () => {
  it("lista marcações sem controles de edição e com filtro por data", async () => {
    routes["GET /api/companies/7/time-records/"] = () => ({
      body: { count: 1, next: null, previous: null, results: [record()] },
    });
    render(<RecordsTab companyId={7} />);
    expect(await screen.findByText(/NSR 42/)).toBeInTheDocument();
    expect(screen.getByText(/21\/10\/2026 23:30:15/)).toBeInTheDocument();
    expect(screen.getByText(/Entrada/)).toBeInTheDocument();
    expect(screen.getByText(/não podem ser editados nem apagados/)).toBeInTheDocument();
    for (const name of [/editar/i, /apagar/i, /excluir/i, /alterar/i]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    fireEvent.change(screen.getByLabelText("De"), { target: { value: "2026-10-01" } });
    await waitFor(() => expect(calls.some((c) => c.key.includes("from=2026-10-01"))).toBe(true));
  });

  it("indica marcação offline e erro de permissão", async () => {
    routes["GET /api/companies/7/time-records/"] = () => ({
      body: { count: 1, next: null, previous: null, results: [record({ offline: true })] },
    });
    const { unmount } = render(<RecordsTab companyId={7} />);
    expect(await screen.findByText(/registrada offline/)).toBeInTheDocument();
    unmount();
    routes["GET /api/companies/7/time-records/"] = () => ({ status: 403 });
    render(<RecordsTab companyId={7} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("permissão");
  });
});

describe("EmployerTab", () => {
  const employer = { legal_name: "", tax_id_type: "", tax_id: "", cei_caepf_cno: "" };

  it("administrador salva os dados do empregador", async () => {
    routes["GET /api/companies/7/employer/"] = () => ({ body: employer });
    routes["PATCH /api/companies/7/employer/"] = () => ({
      body: {
        ...employer,
        legal_name: "Empresa A Ltda",
        tax_id_type: "CNPJ",
        tax_id: "11222333000181",
      },
    });
    render(<EmployerTab companyId={7} canEdit />);
    fireEvent.change(await screen.findByLabelText("Razão social ou nome"), {
      target: { value: "Empresa A Ltda" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Salvar dados do empregador" }));
    expect(await screen.findByText("Dados salvos.")).toBeInTheDocument();
    const patch = calls.find((c) => c.key.startsWith("PATCH"))!;
    expect(JSON.parse(patch.init!.body as string).legal_name).toBe("Empresa A Ltda");
  });

  it("gestor só consulta e erro de validação é exibido", async () => {
    routes["GET /api/companies/7/employer/"] = () => ({ body: employer });
    const { unmount } = render(<EmployerTab companyId={7} canEdit={false} />);
    expect(await screen.findByLabelText("Razão social ou nome")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Salvar/ })).not.toBeInTheDocument();
    unmount();
    routes["PATCH /api/companies/7/employer/"] = () => ({
      status: 400,
      body: { tax_id: ["CNPJ inválido."] },
    });
    render(<EmployerTab companyId={7} canEdit />);
    fireEvent.click(await screen.findByRole("button", { name: "Salvar dados do empregador" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("CNPJ inválido.");
  });
});

describe("RecordsTab: marcações offline", () => {
  it("mostra as sinalizações de revisão com rótulos legíveis", async () => {
    routes["GET /api/companies/7/time-records/"] = () => ({
      body: {
        count: 1,
        next: null,
        previous: null,
        results: [
          record({
            offline: true,
            sync_flags: ["clock_skew_large", "employee_inactive", "codigo_novo"],
          }),
        ],
      },
    });
    render(<RecordsTab companyId={7} />);
    expect(await screen.findByText(/registrada offline/)).toBeInTheDocument();
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent("relógio do tablet com desvio acima de 30 s");
    expect(note).toHaveTextContent("funcionário inativo na sincronização");
    expect(note).toHaveTextContent("codigo_novo"); // sinalização desconhecida aparece sem rótulo
  });

  it("não mostra aviso quando não há sinalização (e tolera registro sem o campo)", async () => {
    routes["GET /api/companies/7/time-records/"] = () => ({
      body: {
        count: 2,
        next: null,
        previous: null,
        results: [
          record({ id: 1, sync_flags: [] }),
          { ...record({ id: 2 }), sync_flags: undefined },
        ],
      },
    });
    render(<RecordsTab companyId={7} />);
    await screen.findAllByText(/NSR 42/);
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("filtra por origem offline", async () => {
    routes["GET /api/companies/7/time-records/"] = () => ({
      body: { count: 0, next: null, previous: null, results: [] },
    });
    render(<RecordsTab companyId={7} />);
    fireEvent.change(await screen.findByLabelText("Origem"), { target: { value: "true" } });
    await waitFor(() => expect(calls.some((c) => c.key.includes("offline=true"))).toBe(true));
    fireEvent.change(screen.getByLabelText("Origem"), { target: { value: "false" } });
    await waitFor(() => expect(calls.some((c) => c.key.includes("offline=false"))).toBe(true));
  });
});
