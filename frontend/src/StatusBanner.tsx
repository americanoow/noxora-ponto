import { useEffect, useState } from "react";
import { type ApiStatus, fetchApiStatus } from "./api";

export function StatusBanner() {
  const [status, setStatus] = useState<ApiStatus>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    fetchApiStatus(controller.signal)
      .then(setStatus)
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  return (
    <div>
      {status.kind === "loading" && <p role="status">Verificando se o sistema está no ar…</p>}
      {status.kind === "ok" && <p role="status">O sistema está funcionando normalmente.</p>}
      {status.kind === "error" && <p role="alert">{status.message}</p>}
    </div>
  );
}
