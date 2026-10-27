import { useEffect, useState } from "react";
import { Shell } from "./Shell";
import { LoginScreen, MfaScreen, ResetScreen } from "./features/AuthScreens";
import { useObservable } from "./lib/observable";
import { Session, SessionContext } from "./lib/session";
import { StatusBanner } from "./StatusBanner";
import "./ui/theme.css";

export function App() {
  const [session] = useState(() => new Session());
  const status = useObservable(session, (s) => s.status);
  const isReset = window.location.pathname === "/redefinir-senha";

  useEffect(() => {
    if (!isReset) void session.load();
  }, [session, isReset]);

  let body;
  if (isReset) {
    const params = new URLSearchParams(window.location.search);
    body = <ResetScreen uid={params.get("uid") ?? ""} token={params.get("token") ?? ""} />;
  } else if (status === "loading") {
    body = (
      <main className="auth">
        <p role="status">Carregando…</p>
      </main>
    );
  } else if (status === "error") {
    body = (
      <main className="auth">
        <div className="auth-panel">
          <p role="alert">Não foi possível contatar a API.</p>
          <StatusBanner />
        </div>
      </main>
    );
  } else if (status === "anonymous") {
    body = <LoginScreen />;
  } else if (status === "mfa") {
    body = <MfaScreen />;
  } else {
    body = <Shell />;
  }
  return <SessionContext.Provider value={session}>{body}</SessionContext.Provider>;
}
