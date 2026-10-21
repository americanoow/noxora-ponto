export type ApiStatus =
  | { kind: "loading" }
  | { kind: "ok"; health: string; database: string }
  | { kind: "error"; message: string };

async function getJson(path: string, signal?: AbortSignal) {
  const response = await fetch(path, { signal });
  const body = await response.json().catch(() => ({}));
  return { ok: response.ok, body };
}

export async function fetchApiStatus(signal?: AbortSignal): Promise<ApiStatus> {
  try {
    const health = await getJson("/api/health/", signal);
    if (!health.ok) return { kind: "error", message: "A API não respondeu corretamente." };
    const ready = await getJson("/api/ready/", signal);
    if (!ready.ok)
      return { kind: "error", message: "A API está no ar, mas o banco está indisponível." };
    return {
      kind: "ok",
      health: String(health.body.status),
      database: String(ready.body.database),
    };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return { kind: "error", message: "Não foi possível contatar a API." };
  }
}
