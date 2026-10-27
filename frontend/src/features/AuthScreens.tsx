import { type FormEvent, type ReactNode, useState } from "react";
import { requestPasswordReset } from "../auth";
import { useSession } from "../lib/session";
import { useAction } from "../lib/task";
import { ErrorText } from "../ui/kit";
import { ResetPasswordScreen } from "../screens";

export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="auth">
      <div className="auth-panel">
        <div className="brand">
          <span className="brand-mark">
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.4"
              aria-hidden="true"
            >
              <path d="M12 7v5l3 2" />
              <circle cx="12" cy="12" r="9" />
            </svg>
          </span>
          Noxora Ponto
        </div>
        {children}
      </div>
    </main>
  );
}

export function LoginScreen() {
  const session = useSession();
  const { pending, error, run } = useAction();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [forgot, setForgot] = useState(false);
  const [sent, setSent] = useState(false);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      if (forgot) {
        await requestPasswordReset(email);
        setSent(true);
      } else {
        await session.signIn(email, password);
      }
    });
  };

  return (
    <AuthLayout>
      <h1>{forgot ? "Recuperar acesso" : "Entrar"}</h1>
      <form onSubmit={submit}>
        <label className="field">
          E-mail
          <input
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        {!forgot && (
          <label className="field">
            Senha
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
        )}
        <ErrorText message={error} />
        {sent && <p role="status">Se o e-mail estiver cadastrado, enviaremos as instruções.</p>}
        <button type="submit" disabled={pending}>
          {forgot ? "Enviar instruções" : "Entrar"}
        </button>
        <button
          type="button"
          className="plain"
          onClick={() => {
            setForgot(!forgot);
            setSent(false);
          }}
        >
          {forgot ? "Voltar ao login" : "Esqueci minha senha"}
        </button>
      </form>
    </AuthLayout>
  );
}

export function MfaScreen() {
  const session = useSession();
  const { pending, error, run } = useAction();
  const [code, setCode] = useState("");
  return (
    <AuthLayout>
      <h1>Verificação em duas etapas</h1>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(() => session.confirmMfa(code));
        }}
      >
        <label className="field">
          Código do aplicativo autenticador ou de recuperação
          <input
            inputMode="text"
            autoComplete="one-time-code"
            value={code}
            onChange={(e) => setCode(e.target.value.trim())}
            required
            autoFocus
          />
        </label>
        <ErrorText message={error} />
        <button type="submit" disabled={pending}>
          Confirmar
        </button>
        <button type="button" className="plain" onClick={session.cancelMfa}>
          Usar outra conta
        </button>
      </form>
    </AuthLayout>
  );
}

export function ResetScreen({ uid, token }: { uid: string; token: string }) {
  return (
    <AuthLayout>
      <div className="auth-reset">
        <ResetPasswordScreen uid={uid} token={token} />
      </div>
    </AuthLayout>
  );
}
