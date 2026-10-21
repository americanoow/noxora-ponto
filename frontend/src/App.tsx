import { useEffect, useState } from "react";
import { type ApiStatus, fetchApiStatus } from "./api";

export function App() {
  const [status, setStatus] = useState<ApiStatus>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    fetchApiStatus(controller.signal)
      .then(setStatus)
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 480, margin: "4rem auto" }}>
      <h1>Noxora Ponto</h1>
      {status.kind === "loading" && <p role="status">Verificando a API…</p>}
      {status.kind === "ok" && (
        <p role="status">
          API disponível (saúde: {status.health}, banco: {status.database}).
        </p>
      )}
      {status.kind === "error" && <p role="alert">{status.message}</p>}
    </main>
  );
}
