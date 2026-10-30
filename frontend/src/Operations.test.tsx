import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  it("exige prévia válida e a invalida ao editar o CSV", async () => {
    routes["GET /api/companies/7/employees/"] = () => ({ body: page([]) });
    routes["POST /api/companies/7/employees/import/"] = () => ({
      body: { total: 1, valid: 1, committed: 0, errors: [] },
    });
    render(<Operations companyId={7} canEdit />);
    fireEvent.click(screen.getByRole("button", { name: "Cadastrar vários" }));
    const submit = screen.getByRole("button", { name: "Cadastrar todos" });
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Ver prévia" }));
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Dados da planilha"), {
      target: { value: "matricula,nome\n1,Ana" },
    });
    expect(submit).toBeDisabled();
  });

  it("descarta dados, busca e formulários ao trocar de empresa", async () => {
    routes["GET /api/companies/7/employees/"] = () => ({ body: page([employee(1, "Privada")]) });
    const { rerender } = render(<Operations companyId={7} canEdit />);
    await screen.findByText(/Privada/);
    fireEvent.change(screen.getByLabelText("Matrícula"), { target: { value: "rascunho" } });
    fireEvent.change(screen.getByLabelText("Buscar"), { target: { value: "Privada" } });
    routes["GET /api/companies/8/employees/"] = () => ({ status: 403 });
    rerender(<Operations companyId={8} canEdit />);
    expect(screen.queryByText(/Privada/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Buscar")).toHaveValue("");
    expect(screen.getByLabelText("Matrícula")).toHaveValue("");
    await screen.findByRole("alert");
    expect(screen.queryByText(/Privada/)).not.toBeInTheDocument();
  });

  it("ignora resposta antiga que chega depois da busca mais recente", async () => {
    let resolveOld!: (value: unknown) => void;
    const old = new Promise((resolve) => {
      resolveOld = resolve;
    });
    const original = globalThis.fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string, init?: RequestInit) => {
        if (input.includes("/employees/")) {
          if (!input.includes("q=")) return old;
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => page([employee(2, "Nova")]),
          });
        }
        return original(input, init);
      }),
    );
    render(<Operations companyId={7} canEdit />);
    fireEvent.change(screen.getByLabelText("Buscar"), { target: { value: "Nova" } });
    await screen.findByText(/Nova/);
    await act(async () => {
      resolveOld({ ok: true, status: 200, json: async () => page([employee(1, "Antiga")]) });
    });
    expect(screen.queryByText(/Antiga/)).not.toBeInTheDocument();
    expect(screen.getByText(/Nova/)).toBeInTheDocument();
  });

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
    expect(screen.queryByRole("button", { name: "Cadastrar vários" })).not.toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "Cadastrar vários" }));
    fireEvent.click(screen.getByRole("button", { name: "Ver prévia" }));
    expect(await screen.findByText(/Linha 3 \(cpf\): CPF inválido\./)).toBeInTheDocument();
    const post = calls.find((c) => c.key.startsWith("POST"))!;
    expect(JSON.parse(post.init!.body as string).commit).toBe(false);
  });
});
