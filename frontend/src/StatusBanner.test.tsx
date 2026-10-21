import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StatusBanner } from "./StatusBanner";

const respond = (ok: boolean, body: object) =>
  Promise.resolve({ ok, json: () => Promise.resolve(body) });

afterEach(() => vi.unstubAllGlobals());

describe("StatusBanner", () => {
  it("mostra carregamento e depois sucesso", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.includes("health")
          ? respond(true, { status: "ok" })
          : respond(true, { status: "ok", database: "ok" }),
      ),
    );
    render(<StatusBanner />);
    expect(screen.getByRole("status")).toHaveTextContent("Verificando");
    expect(await screen.findByText(/API disponível/)).toBeInTheDocument();
  });

  it("mostra falha quando o banco está indisponível", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.includes("health")
          ? respond(true, { status: "ok" })
          : respond(false, { database: "falha" }),
      ),
    );
    render(<StatusBanner />);
    expect(await screen.findByRole("alert")).toHaveTextContent("banco está indisponível");
  });

  it("mostra falha quando a API não responde", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("rede"))),
    );
    render(<StatusBanner />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível contatar");
  });
});
