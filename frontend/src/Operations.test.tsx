import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Operations } from "./Operations";
import { resetCsrf } from "./http";

let routes: Record<string, (init?: RequestInit) => { status?: number; body?: unknown }>;
let calls: { key: string; init?: RequestInit }[];

const employee = (id: number, name: string) => ({
  id,
  registration: String(id),
  full_name: name,
  cpf: "***.***.***-25",
  is_active: true,
  unit: { id: 1, name: "Centro" },
  sector: null,
});

beforeEach(() => {
  calls = [];
  resetCsrf();
  routes = {
    "GET /api/auth/csrf/": () => ({ body: { csrfToken: "tok" } }),
    "GET /api/companies/7/units/": () => ({
      body: [{ id: 1, name: "Centro", timezone: "America/Sao_Paulo", is_active: true }],
    }),
    "GET /api/companies/7/sectors/": () => ({ body: [] }),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      const path = url.split("?")[0];
      const key = `${init?.method ?? "GET"} ${path}`;
      calls.push({ key: `${init?.method ?? "GET"} ${url}`, init });
      const handler = routes[key];
      const { status = 200, body = {} } = handler ? handler(init) : { status: 404 };
      return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

const page = (results: unknown[], count = results.length) => ({
  count,
  next: null,
  previous: null,
  results,
});

describe("Operations", () => {
  it("lista funcionários com CPF mascarado e busca com filtro", async () => {
    routes["GET /api/companies/7/employees/"] = () => ({ body: page([employee(1, "Ana")], 1) });
    render(<Operations companyId={7} canEdit />);
    expect(await screen.findByText(/Ana/)).toBeInTheDocument();
    expect(screen.getByText(/\*\*\*\.\*\*\*\.\*\*\*-25/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Buscar"), { target: { value: "ana" } });
    await waitFor(() => expect(calls.some((c) => c.key.includes("q=ana"))).toBe(true));
  });

  it("gestor não vê formulários de escrita nem a aba de importação", async () => {
    routes["GET /api/companies/7/employees/"] = () => ({ body: page([employee(1, "Ana")]) });
    render(<Operations companyId={7} canEdit={false} />);
    expect(await screen.findByText(/Ana/)).toBeInTheDocument();
    expect(screen.queryByText("Novo funcionário")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Importação" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Inativar" })).not.toBeInTheDocument();
  });

  it("mostra erro de permissão quando a API nega", async () => {
    routes["GET /api/companies/7/employees/"] = () => ({ status: 403, body: {} });
    render(<Operations companyId={7} canEdit />);
    expect(await screen.findByRole("alert")).toHaveTextContent("permissão");
  });

  it("paginação habilita 'Próxima' só quando há próxima página", async () => {
    routes["GET /api/companies/7/employees/"] = () => ({
      body: { count: 40, next: "x", previous: null, results: [employee(1, "Ana")] },
    });
    render(<Operations companyId={7} canEdit />);
    await screen.findByText(/Ana/);
    expect(screen.getByRole("button", { name: "Anterior" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Próxima" }));
    await waitFor(() => expect(calls.some((c) => c.key.includes("page=2"))).toBe(true));
  });

  it("importação mostra erros por linha da prévia", async () => {
    routes["GET /api/companies/7/employees/"] = () => ({ body: page([]) });
    routes["POST /api/companies/7/employees/import/"] = () => ({
      body: {
        total: 2,
        valid: 1,
        committed: 0,
        errors: [{ line: 3, field: "cpf", message: "CPF inválido." }],
      },
    });
    render(<Operations companyId={7} canEdit />);
    fireEvent.click(screen.getByRole("button", { name: "Importação" }));
    fireEvent.click(screen.getByRole("button", { name: "Pré-visualizar" }));
    expect(await screen.findByText(/Linha 3 \(cpf\): CPF inválido\./)).toBeInTheDocument();
    const post = calls.find((c) => c.key.startsWith("POST"))!;
    expect(JSON.parse(post.init!.body as string).commit).toBe(false);
  });
});
