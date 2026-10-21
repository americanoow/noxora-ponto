import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { login, logout } from "./auth";
import { ApiError, request, resetCsrf } from "./http";

beforeEach(() => resetCsrf());
afterEach(() => vi.unstubAllGlobals());

function response(status: number, body: unknown) {
  return { ok: status < 400, status, json: async () => body };
}

it("renova CSRF após login e logout", async () => {
  let generation = 0;
  const tokens: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("csrf/")) return response(200, { csrfToken: `token-${++generation}` });
      tokens.push((init?.headers as Record<string, string>)["X-CSRFToken"]);
      return response(url.endsWith("logout/") ? 204 : 200, {});
    }),
  );
  await login("a@a.test", "senha");
  await logout();
  await request("POST", "/api/auth/password-reset/", { email: "a@a.test" });
  expect(tokens).toEqual(["token-1", "token-2", "token-3"]);
});

it("falha ao buscar CSRF impede mutação e preserva status 429", async () => {
  const fetchMock = vi.fn(async () => response(429, { detail: "Limite" }));
  vi.stubGlobal("fetch", fetchMock);
  await expect(request("POST", "/api/auth/login/", {})).rejects.toMatchObject({ status: 429 });
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("403 descarta CSRF para próxima tentativa sem repetir mutação automaticamente", async () => {
  let generation = 0;
  const tokens: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("csrf/")) return response(200, { csrfToken: `token-${++generation}` });
      tokens.push((init?.headers as Record<string, string>)["X-CSRFToken"]);
      return response(tokens.length === 1 ? 403 : 200, {});
    }),
  );
  await expect(request("POST", "/api/auth/logout/")).rejects.toBeInstanceOf(ApiError);
  expect(tokens).toEqual(["token-1"]);
  await request("POST", "/api/auth/logout/");
  expect(tokens).toEqual(["token-1", "token-2"]);
});
