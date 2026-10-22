import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DevicesTab } from "./DevicesTab";
import { resetCsrf } from "./http";

let routes: Record<string, (init?: RequestInit) => { status?: number; body?: unknown }>;
let calls: { key: string; init?: RequestInit }[];

const device = (over = {}) => ({
  id: 1,
  name: "Tablet Recepção",
  unit: 1,
  unit_name: "Centro",
  status: "active",
  last_seen_at: "2026-10-21T12:00:00Z",
  app_version: "1.2.0",
  connectivity: "online",
  collect_location: false,
  location_justification: "",
  ...over,
});

beforeEach(() => {
  calls = [];
  resetCsrf();
  routes = {
    "GET /api/auth/csrf/": () => ({ body: { csrfToken: "tok" } }),
    "GET /api/companies/7/devices/": () => ({ body: [device()] }),
    "GET /api/companies/7/units/": () => ({
      body: [{ id: 1, name: "Centro", timezone: "America/Sao_Paulo", is_active: true }],
    }),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url}`;
      calls.push({ key, init });
      const handler = routes[key];
      const { status = 200, body = {} } = handler ? handler(init) : { status: 404 };
      return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("DevicesTab", () => {
  it("lista tablets com situação, conectividade e versão", async () => {
    render(<DevicesTab companyId={7} canEdit />);
    expect(await screen.findByText(/Tablet Recepção/)).toBeInTheDocument();
    expect(screen.getByText(/Online/)).toBeInTheDocument();
    expect(screen.getByText(/versão 1\.2\.0/)).toBeInTheDocument();
  });

  it("mostra o código de ativação uma vez e permite ocultá-lo", async () => {
    routes["POST /api/companies/7/devices/"] = () => ({
      status: 201,
      body: {
        ...device({ status: "pending", connectivity: "never" }),
        activation_code: "ABCDE-FGHJK",
        activation_expires_at: "2026-10-21T12:15:00Z",
      },
    });
    render(<DevicesTab companyId={7} canEdit />);
    await screen.findByText(/Tablet Recepção/);
    fireEvent.change(screen.getByLabelText("Nome do tablet"), { target: { value: "Novo" } });
    fireEvent.change(screen.getByLabelText("Unidade do tablet"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Cadastrar e gerar código" }));
    expect(await screen.findByLabelText("Código de ativação")).toHaveTextContent("ABCDE-FGHJK");
    fireEvent.click(screen.getByRole("button", { name: "Ocultar" }));
    expect(screen.queryByText("ABCDE-FGHJK")).not.toBeInTheDocument();
  });

  it("gestor só consulta: sem criar, revogar ou renovar", async () => {
    render(<DevicesTab companyId={7} canEdit={false} />);
    await screen.findByText(/Tablet Recepção/);
    expect(screen.queryByText("Novo tablet")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Revogar" })).not.toBeInTheDocument();
    expect(calls.some((c) => c.key.includes("/units/"))).toBe(false);
  });

  it("mantém o código só em memória e o descarta ao mudar empresa ou permissão", async () => {
    const localWrite = vi.spyOn(Storage.prototype, "setItem");
    routes["POST /api/companies/7/devices/1/activation-code/"] = () => ({
      body: {
        ...device(),
        activation_code: "ABCDE-FGHJK",
        activation_expires_at: "2026-10-21T12:15:00Z",
      },
    });
    const view = render(<DevicesTab companyId={7} canEdit />);
    fireEvent.click(await screen.findByRole("button", { name: "Renovar (novo código)" }));
    expect(await screen.findByLabelText("Código de ativação")).toHaveTextContent("ABCDE-FGHJK");
    expect(localWrite).not.toHaveBeenCalled();
    view.rerender(<DevicesTab companyId={7} canEdit={false} />);
    await screen.findByText(/Tablet Recepção/);
    expect(screen.queryByLabelText("Código de ativação")).not.toBeInTheDocument();
    view.rerender(<DevicesTab companyId={8} canEdit />);
    await screen.findByRole("alert");
    expect(screen.queryByLabelText("Código de ativação")).not.toBeInTheDocument();
    localWrite.mockRestore();
  });

  it("revoga um tablet", async () => {
    routes["POST /api/companies/7/devices/1/revoke/"] = () => ({
      body: device({ status: "revoked" }),
    });
    render(<DevicesTab companyId={7} canEdit />);
    fireEvent.click(await screen.findByRole("button", { name: "Revogar" }));
    await waitFor(() =>
      expect(calls.some((c) => c.key === "POST /api/companies/7/devices/1/revoke/")).toBe(true),
    );
  });

  it("exibe erro de permissão", async () => {
    routes["GET /api/companies/7/devices/"] = () => ({ status: 403 });
    render(<DevicesTab companyId={7} canEdit={false} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("permissão");
  });
});
