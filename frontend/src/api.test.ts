import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchApiStatus } from "./api";

afterEach(() => vi.restoreAllMocks());

describe("contrato da API", () => {
  it.each([null, {}, [], { status: "falha" }])("rejeita health inválido: %j", async (body) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(body)));
    expect((await fetchApiStatus()).kind).toBe("error");
  });

  it.each([null, {}, { database: "ok" }, { status: "ok", database: "falha" }])(
    "rejeita ready inválido: %j",
    async (body) => {
      vi.spyOn(globalThis, "fetch")
        .mockResolvedValueOnce(new Response('{"status":"ok"}'))
        .mockResolvedValueOnce(new Response(JSON.stringify(body)));
      expect((await fetchApiStatus()).kind).toBe("error");
    },
  );

  it("rejeita resposta não JSON", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("<html>proxy</html>"));
    expect((await fetchApiStatus()).kind).toBe("error");
  });

  it("trata timeout como falha e preserva cancelamento", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new DOMException("tempo esgotado", "TimeoutError"))
      .mockRejectedValueOnce(new DOMException("cancelado", "AbortError"));
    expect((await fetchApiStatus()).kind).toBe("error");
    expect(fetchMock.mock.calls[0][1]?.signal).toBeInstanceOf(AbortSignal);
    await expect(fetchApiStatus()).rejects.toMatchObject({ name: "AbortError" });
  });
});
