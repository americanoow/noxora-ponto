import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ImportTab, SchedulesTab, UnitsTab } from "./Operations";
import { resetCsrf } from "./http";

let routes: Record<string, (init?: RequestInit) => { status?: number; body?: unknown }>;
let calls: { key: string; init?: RequestInit }[];

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

describe("Cadastro em lote e estrutura", () => {
  it("exige prévia válida e a invalida ao editar o CSV", async () => {
    routes["POST /api/companies/7/employees/import/"] = () => ({
      body: { total: 1, valid: 1, committed: 0, errors: [] },
    });
    render(<ImportTab companyId={7} />);
    const submit = screen.getByRole("button", { name: "Cadastrar todos" });
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Ver prévia" }));
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Dados da planilha"), {
      target: { value: "matricula,nome\n1,Ana" },
    });
    expect(submit).toBeDisabled();
  });

  it("importação mostra erros por linha da prévia", async () => {
    routes["POST /api/companies/7/employees/import/"] = () => ({
      body: {
        total: 2,
        valid: 1,
        committed: 0,
        errors: [{ line: 3, field: "cpf", message: "CPF inválido." }],
      },
    });
    render(<ImportTab companyId={7} />);
    fireEvent.click(screen.getByRole("button", { name: "Ver prévia" }));
    expect(await screen.findByText(/Linha 3 \(cpf\): CPF inválido\./)).toBeInTheDocument();
    const post = calls.find((c) => c.key.startsWith("POST"))!;
    expect(JSON.parse(post.init!.body as string).commit).toBe(false);
  });

  it("gestor vê unidades e horários sem formulários de escrita", async () => {
    routes["GET /api/companies/7/schedules/"] = () => ({ body: [] });
    render(<UnitsTab companyId={7} canEdit={false} />);
    expect(await screen.findByText("Centro")).toBeInTheDocument();
    expect(screen.queryByLabelText("Nome da unidade")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Inativar" })).not.toBeInTheDocument();
    render(<SchedulesTab companyId={7} canEdit={false} />);
    await waitFor(() => expect(calls.some((c) => c.key.endsWith("/schedules/"))).toBe(true));
    expect(screen.queryByLabelText(/Nome do horário de trabalho/)).not.toBeInTheDocument();
  });

  it("administrador cria unidade", async () => {
    routes["POST /api/companies/7/units/"] = () => ({ status: 201, body: { id: 2 } });
    render(<UnitsTab companyId={7} canEdit />);
    await screen.findAllByText("Centro");
    fireEvent.change(screen.getByLabelText("Nome da unidade"), { target: { value: "Filial" } });
    fireEvent.submit(screen.getByLabelText("Nome da unidade").closest("form")!);
    await waitFor(() =>
      expect(calls.some((c) => c.key === "POST /api/companies/7/units/")).toBe(true),
    );
  });
});
