import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BiometricsActions, IdentificationModePanel } from "./BiometricsActions";
import { resetCsrf } from "./http";

let routes: Record<string, (init?: RequestInit) => { status?: number; body?: unknown }>;
let calls: { key: string; init?: RequestInit }[];

const status = (over = {}) => ({
  employee_id: 5,
  consent: null,
  template: null,
  engine: { name: "simulator", version: "0", simulator: true },
  ...over,
});

beforeEach(() => {
  calls = [];
  resetCsrf();
  routes = { "GET /api/auth/csrf/": () => ({ body: { csrfToken: "tok" } }) };
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url}`;
      calls.push({ key, init });
      const handler = routes[key];
      const { status: code = 200, body = {} } = handler ? handler(init) : { status: 404 };
      return Promise.resolve({ ok: code < 400, status: code, json: () => Promise.resolve(body) });
    }),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const props = { companyId: 7, employeeId: 5, employeeName: "Maria" };

describe("BiometricsActions", () => {
  it("administrador vê o status, o aviso do simulador e registra o consentimento", async () => {
    routes["GET /api/companies/7/employees/5/biometric/"] = () => ({ body: status() });
    routes["POST /api/companies/7/employees/5/biometric/consent/"] = () => ({
      status: 201,
      body: status({ consent: { policy_version: "v2", granted_at: "2026-10-22T00:00:00Z" } }),
    });
    render(<BiometricsActions {...props} canEdit />);
    fireEvent.click(screen.getByRole("button", { name: "Identificação no tablet" }));
    expect(await screen.findByText(/Reconhecimento facial de TESTE/)).toBeInTheDocument();
    expect(screen.getByText(/não garante quem é a pessoa/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Versão do termo de autorização"), {
      target: { value: "v2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Registrar autorização" }));
    expect(
      await screen.findByText(/Autorização para usar o rosto: registrada/),
    ).toBeInTheDocument();
    const post = calls.find((c) =>
      c.key.startsWith("POST /api/companies/7/employees/5/biometric/consent"),
    )!;
    expect(JSON.parse(post.init!.body as string).policy_version).toBe("v2");
  });

  it("gestor não vê controles de biometria, só a exceção, e o código aparece uma vez", async () => {
    routes["POST /api/companies/7/employees/5/identification-exceptions/"] = () => ({
      status: 201,
      body: { authorization_id: 9, code: "12345678", expires_at: "2026-10-22T00:15:00Z" },
    });
    vi.spyOn(window, "prompt").mockReturnValue("Câmera danificada");
    render(<BiometricsActions {...props} canEdit={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Identificação no tablet" }));
    expect(screen.queryByText(/Rosto cadastrado/)).not.toBeInTheDocument();
    expect(calls.some((c) => c.key.includes("/biometric/"))).toBe(false);
    fireEvent.click(
      screen.getByRole("button", { name: "Liberar bater o ponto sem reconhecimento facial" }),
    );
    expect(await screen.findByLabelText("Código liberado")).toHaveTextContent("12345678");
    fireEvent.click(screen.getByRole("button", { name: "Ocultar" }));
    expect(screen.queryByText("12345678")).not.toBeInTheDocument();
    expect(
      JSON.parse(calls.find((c) => c.key.startsWith("POST"))!.init!.body as string).reason,
    ).toBe("Câmera danificada");
  });

  it("não chama a API quando o motivo da exceção é cancelado", () => {
    vi.spyOn(window, "prompt").mockReturnValue(null);
    render(<BiometricsActions {...props} canEdit={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Identificação no tablet" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Liberar bater o ponto sem reconhecimento facial" }),
    );
    expect(calls.some((c) => c.key.startsWith("POST"))).toBe(false);
  });

  it("mostra erro de permissão e exclui o cadastro facial", async () => {
    routes["GET /api/companies/7/employees/5/biometric/"] = () => ({
      body: status({
        consent: { policy_version: "v1", granted_at: "x" },
        template: { engine: "simulator", engine_version: "0", created_at: "x", quality: 1 },
      }),
    });
    routes["DELETE /api/companies/7/employees/5/biometric/"] = () => ({
      body: status({ consent: { policy_version: "v1", granted_at: "x" } }),
    });
    render(<BiometricsActions {...props} canEdit />);
    fireEvent.click(screen.getByRole("button", { name: "Identificação no tablet" }));
    fireEvent.click(await screen.findByRole("button", { name: "Apagar o rosto cadastrado" }));
    await waitFor(() => expect(screen.getByText(/Rosto cadastrado: não/)).toBeInTheDocument());
  });

  it("não envia imagem sem seleção de arquivo", async () => {
    routes["GET /api/companies/7/employees/5/biometric/"] = () => ({
      body: status({ consent: { policy_version: "v1", granted_at: "x" } }),
    });
    render(<BiometricsActions {...props} canEdit />);
    fireEvent.click(screen.getByRole("button", { name: "Identificação no tablet" }));
    const input = await screen.findByLabelText(/Fotos do rosto para o cadastro/);
    fireEvent.change(input, { target: { files: [] } });
    expect(calls.some((c) => c.key.includes("/enroll/"))).toBe(false);
  });
});

describe("IdentificationModePanel", () => {
  it("administrador troca para o modo facial e vê o aviso", async () => {
    routes["GET /api/companies/7/identification/"] = () => ({ body: { mode: "registration" } });
    routes["PATCH /api/companies/7/identification/"] = () => ({ body: { mode: "face" } });
    render(<IdentificationModePanel companyId={7} canEdit />);
    fireEvent.change(await screen.findByLabelText("Como o funcionário se identifica"), {
      target: { value: "face" },
    });
    expect(await screen.findByText(/não estiver configurado no sistema/)).toBeInTheDocument();
  });

  it("gestor só consulta", async () => {
    routes["GET /api/companies/7/identification/"] = () => ({ body: { mode: "face" } });
    render(<IdentificationModePanel companyId={7} canEdit={false} />);
    expect(await screen.findByLabelText("Como o funcionário se identifica")).toBeDisabled();
  });
});

it("fechar e reabrir não reapresenta o código de exceção", async () => {
  routes["POST /api/companies/7/employees/5/identification-exceptions/"] = () => ({
    body: { authorization_id: 9, code: "12345678", expires_at: "2026-10-22T00:15:00Z" },
  });
  vi.spyOn(window, "prompt").mockReturnValue("Câmera danificada");
  render(<BiometricsActions {...props} canEdit={false} />);
  fireEvent.click(screen.getByRole("button", { name: "Identificação no tablet" }));
  fireEvent.click(
    screen.getByRole("button", { name: "Liberar bater o ponto sem reconhecimento facial" }),
  );
  expect(await screen.findByLabelText("Código liberado")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Identificação no tablet" }));
  fireEvent.click(screen.getByRole("button", { name: "Identificação no tablet" }));
  expect(screen.queryByLabelText("Código liberado")).not.toBeInTheDocument();
});

it("recusa imagens grandes antes de ler ou enviar e limpa o seletor", async () => {
  routes["GET /api/companies/7/employees/5/biometric/"] = () => ({
    body: status({ consent: { policy_version: "v1", granted_at: "x" } }),
  });
  const read = vi.spyOn(FileReader.prototype, "readAsDataURL");
  render(<BiometricsActions {...props} canEdit />);
  fireEvent.click(screen.getByRole("button", { name: "Identificação no tablet" }));
  const input = await screen.findByLabelText(/Fotos do rosto para o cadastro/);
  fireEvent.change(input, {
    target: { files: [new File([new Uint8Array(1_000_001)], "foto.jpg")] },
  });
  expect(await screen.findByRole("alert")).toHaveTextContent(/máximo 1 MB/);
  expect(read).not.toHaveBeenCalled();
  expect(calls.some((c) => c.key.includes("/enroll/"))).toBe(false);
  expect(input).toHaveValue("");
});

describe("IdentificationModePanel: política offline", () => {
  it("administrador ativa a marcação offline e vê o aviso de limitação", async () => {
    routes["GET /api/companies/7/identification/"] = () => ({
      body: { mode: "registration", offline_policy: "disabled" },
    });
    routes["PATCH /api/companies/7/identification/"] = () => ({
      body: { mode: "registration", offline_policy: "registration_only" },
    });
    render(<IdentificationModePanel companyId={7} canEdit />);
    const select = await screen.findByLabelText("Bater o ponto sem internet");
    expect(select).toHaveValue("disabled");
    expect(
      screen.getByText(/O reconhecimento facial não funciona sem internet/),
    ).toBeInTheDocument();
    fireEvent.change(select, { target: { value: "registration_only" } });
    await waitFor(() =>
      expect(screen.getByLabelText("Bater o ponto sem internet")).toHaveValue("registration_only"),
    );
    const patch = calls.find((c) => c.key.startsWith("PATCH"))!;
    expect(JSON.parse(patch.init!.body as string)).toEqual({ offline_policy: "registration_only" });
  });

  it("gestor só consulta; resposta antiga sem o campo assume desativada", async () => {
    routes["GET /api/companies/7/identification/"] = () => ({ body: { mode: "registration" } });
    render(<IdentificationModePanel companyId={7} canEdit={false} />);
    const select = await screen.findByLabelText("Bater o ponto sem internet");
    expect(select).toBeDisabled();
    expect(select).toHaveValue("disabled");
  });

  it("exibe erro de permissão ao alterar", async () => {
    routes["GET /api/companies/7/identification/"] = () => ({
      body: { mode: "registration", offline_policy: "disabled" },
    });
    routes["PATCH /api/companies/7/identification/"] = () => ({ status: 403 });
    render(<IdentificationModePanel companyId={7} canEdit />);
    fireEvent.change(await screen.findByLabelText("Bater o ponto sem internet"), {
      target: { value: "registration_only" },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("permissão");
  });
});
