import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { resetCsrf } from "./http";

type Handler = (init: RequestInit | undefined) => { status?: number; body?: unknown };
let routes: Record<string, Handler>;
let calls: { url: string; init?: RequestInit }[];

const me = (role: string, platform = false) => ({
  id: 1,
  email: "adm@a.test",
  name: "Adm",
  is_platform_admin: platform,
  memberships: [{ id: 1, company_id: 7, company_name: "Empresa A", role }],
});

beforeEach(() => {
  calls = [];
  resetCsrf();
  routes = {
    "GET /api/health/": () => ({ body: { status: "ok" } }),
    "GET /api/ready/": () => ({ body: { status: "ok", database: "ok" } }),
    "GET /api/auth/csrf/": () => ({ body: { csrfToken: "tok" } }),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const handler = routes[`${init?.method ?? "GET"} ${url}`];
      const { status = 200, body = {} } = handler ? handler(init) : { status: 404 };
      return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("mostra o login quando não há sessão", async () => {
    routes["GET /api/auth/me/"] = () => ({ status: 403 });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Entrar" })).toBeInTheDocument();
  });

  it("faz login enviando o token CSRF e mostra a empresa", async () => {
    routes["GET /api/auth/me/"] = () => ({ status: 403 });
    routes["POST /api/auth/login/"] = () => ({ body: me("employee") });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("E-mail"), { target: { value: "adm@a.test" } });
    fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "senha-longa-123" } });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByText(/Funcionário/)).toBeInTheDocument();
    const post = calls.find((c) => c.url === "/api/auth/login/")!;
    expect((post.init!.headers as Record<string, string>)["X-CSRFToken"]).toBe("tok");
  });

  it("mostra erro de credenciais inválidas", async () => {
    routes["GET /api/auth/me/"] = () => ({ status: 403 });
    routes["POST /api/auth/login/"] = () => ({
      status: 400,
      body: { detail: "E-mail ou senha inválidos." },
    });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("E-mail"), { target: { value: "a@a.test" } });
    fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("E-mail ou senha inválidos.");
  });

  it("administrador vê e altera acessos; funcionário não vê o painel", async () => {
    routes["GET /api/auth/me/"] = () => ({ body: me("company_admin") });
    routes["GET /api/companies/7/members/"] = () => ({
      body: [{ id: 5, email: "g@a.test", name: "Gê", role: "manager", is_active: true }],
    });
    routes["PATCH /api/companies/7/members/5/"] = () => ({ body: {} });
    render(<App />);
    expect(await screen.findByText(/g@a.test/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Desativar" }));
    await waitFor(() =>
      expect(calls.some((c) => c.url === "/api/companies/7/members/5/")).toBe(true),
    );
  });

  it("funcionário não carrega a lista de acessos", async () => {
    routes["GET /api/auth/me/"] = () => ({ body: me("employee") });
    render(<App />);
    expect(await screen.findByText(/Somente administradores/)).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("/members/"))).toBe(false);
  });

  it("encerra a sessão ao sair", async () => {
    routes["GET /api/auth/me/"] = () => ({ body: me("employee") });
    routes["POST /api/auth/logout/"] = () => ({ status: 204 });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Sair" }));
    expect(await screen.findByRole("heading", { name: "Entrar" })).toBeInTheDocument();
  });
});

it("mantém sessão visível e informa falha ao sair", async () => {
  routes["GET /api/auth/me/"] = () => ({ body: me("employee") });
  routes["POST /api/auth/logout/"] = () => ({ status: 403 });
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Sair" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Você não tem permissão");
  expect(screen.getByRole("button", { name: "Sair" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Entrar" })).not.toBeInTheDocument();
});

it("descarta membros anteriores ao trocar para empresa que retorna 403", async () => {
  const account = me("company_admin");
  account.memberships.push({
    id: 2,
    company_id: 8,
    company_name: "Empresa B",
    role: "company_admin",
  });
  routes["GET /api/auth/me/"] = () => ({ body: account });
  routes["GET /api/companies/7/members/"] = () => ({
    body: [{ id: 5, email: "privado@a.test", name: "A", role: "employee", is_active: true }],
  });
  routes["GET /api/companies/8/members/"] = () => ({ status: 403 });
  render(<App />);
  expect(await screen.findByText(/privado@a.test/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Empresa"), { target: { value: "8" } });
  expect(await screen.findByRole("alert")).toHaveTextContent("Você não tem permissão");
  expect(screen.queryByText(/privado@a.test/)).not.toBeInTheDocument();
});

it("informa limite de tentativas no login", async () => {
  routes["GET /api/auth/me/"] = () => ({ status: 403 });
  routes["POST /api/auth/login/"] = () => ({ status: 429 });
  render(<App />);
  fireEvent.change(await screen.findByLabelText("E-mail"), { target: { value: "a@a.test" } });
  fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "senha" } });
  fireEvent.click(screen.getByRole("button", { name: "Entrar" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Muitas tentativas");
});
