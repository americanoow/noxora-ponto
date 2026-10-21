import { useEffect, useState } from "react";
import { StatusBanner } from "./StatusBanner";
import { type Me, ROLE_LABELS, errorMessage, fetchMe, logout } from "./auth";
import { LoginScreen, MembersPanel, PlatformPanel, ResetPasswordScreen } from "./screens";

export function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);

  const params = new URLSearchParams(window.location.search);
  const isReset = window.location.pathname === "/redefinir-senha";

  useEffect(() => {
    if (isReset) return;
    fetchMe()
      .then((value) => {
        setMe(value);
        setCompanyId(value?.memberships[0]?.company_id ?? null);
      })
      .catch(() => setLoadError(true));
  }, [isReset]);

  const membership = me?.memberships.find((m) => m.company_id === companyId);

  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 640, margin: "3rem auto" }}>
      <h1>Noxora Ponto</h1>
      {isReset ? (
        <ResetPasswordScreen uid={params.get("uid") ?? ""} token={params.get("token") ?? ""} />
      ) : loadError ? (
        <p role="alert">Não foi possível contatar a API.</p>
      ) : me === undefined ? (
        <p role="status">Carregando…</p>
      ) : me === null ? (
        <LoginScreen
          onLogin={(value) => {
            setMe(value);
            setCompanyId(value.memberships[0]?.company_id ?? null);
          }}
        />
      ) : (
        <>
          <p>
            {me.email}
            {membership && ` — ${ROLE_LABELS[membership.role]}`}{" "}
            <button
              onClick={() =>
                void logout()
                  .then(() => {
                    setMe(null);
                    setCompanyId(null);
                    setLogoutError(null);
                  })
                  .catch((error: unknown) => setLogoutError(errorMessage(error)))
              }
            >
              Sair
            </button>
          </p>
          {logoutError && <p role="alert">{logoutError}</p>}
          {me.memberships.length > 1 && (
            <select
              aria-label="Empresa"
              value={companyId ?? ""}
              onChange={(e) => setCompanyId(Number(e.target.value))}
            >
              {me.memberships.map((m) => (
                <option key={m.id} value={m.company_id}>
                  {m.company_name}
                </option>
              ))}
            </select>
          )}
          {me.is_platform_admin && <PlatformPanel />}
          {membership && (
            <MembersPanel
              key={`${membership.company_id}:${membership.role}`}
              companyId={membership.company_id}
              myRole={membership.role}
            />
          )}
          {!membership && !me.is_platform_admin && (
            <p>Seu usuário não possui acesso a nenhuma empresa.</p>
          )}
        </>
      )}
      <StatusBanner />
    </main>
  );
}
