export class ApiError extends Error {
  constructor(
    public status: number,
    public body: Record<string, unknown>,
  ) {
    super(typeof body.detail === "string" ? body.detail : `Erro ${status}`);
  }
}

let csrfToken: string | null = null;

/** O Django rotaciona o token CSRF no login e no logout: descarte-o ao mudar a sessão. */
export function resetCsrf() {
  csrfToken = null;
}

async function ensureCsrf(): Promise<string> {
  if (csrfToken) return csrfToken;
  const response = await fetch("/api/auth/csrf/", { credentials: "same-origin" });
  const data = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) throw new ApiError(response.status, data);
  if (typeof data.csrfToken !== "string" || !data.csrfToken) throw new Error("Token CSRF ausente.");
  csrfToken = data.csrfToken;
  return csrfToken;
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (method !== "GET") {
    headers["X-CSRFToken"] = await ensureCsrf();
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    // Uma sessão pode ter sido alterada em outra aba; a próxima tentativa precisa de token novo.
    if (response.status === 403) resetCsrf();
    throw new ApiError(response.status, data as Record<string, unknown>);
  }
  return data as T;
}
