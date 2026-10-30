export type ApiStatus =
  | { kind: "loading" }
  | { kind: "ok"; health: string; database: string }
  | { kind: "error"; message: string };

async function getJson(path: string, signal?: AbortSignal) {
  const timeout = AbortSignal.timeout(8000);
  const response = await fetch(path, {
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
  });
  const body: unknown = await response.json();
  return { ok: response.ok, body };
}

function hasOk(body: unknown, field: string): boolean {
  return (
    typeof body === "object" &&
    body !== null &&
    field in body &&
    (body as Record<string, unknown>)[field] === "ok"
  );
}

export async function fetchApiStatus(signal?: AbortSignal): Promise<ApiStatus> {
  try {
    const health = await getJson("/api/health/", signal);
    if (!health.ok || !hasOk(health.body, "status"))
      return {
        kind: "error",
        message: "O sistema não respondeu como esperado. Tente de novo em instantes.",
      };
    const ready = await getJson("/api/ready/", signal);
    if (!ready.ok)
      return {
        kind: "error",
        message:
          "O sistema está no ar, mas não consegue acessar os dados agora. Tente de novo em instantes.",
      };
    if (!hasOk(ready.body, "status") || !hasOk(ready.body, "database"))
      return {
        kind: "error",
        message: "O sistema não respondeu como esperado. Tente de novo em instantes.",
      };
    return {
      kind: "ok",
      health: "ok",
      database: "ok",
    };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return {
      kind: "error",
      message: "Não conseguimos falar com o sistema. Verifique sua internet.",
    };
  }
}
