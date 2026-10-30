import { describe, expect, it } from "vitest";
import { errorMessage } from "./auth";
import { ApiError } from "./http";

describe("errorMessage", () => {
  it("diferencia falha de CSRF de falta de permissão", () => {
    const csrf = new ApiError(403, { detail: "CSRF Failed: Origin checking failed" });
    expect(errorMessage(csrf)).toContain("recarregada");
    expect(errorMessage(csrf)).not.toContain("permissão");
    expect(errorMessage(new ApiError(403, {}))).toContain("Você não tem permissão");
    expect(errorMessage(new ApiError(429, {}))).toContain("muitas vezes");
  });
});
