import { type FormEvent, type ReactNode, useState } from "react";
import { requestPasswordReset } from "../auth";
import { useSession } from "../lib/session";
import { useAction } from "../lib/task";
import { Brand } from "../ui/Brand";
import { ErrorText } from "../ui/kit";
import { ResetPasswordScreen } from "../screens";

export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="auth">
      <div className="auth-panel">
        <Brand />
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
      <h1>{forgot ? "Esqueci minha senha" : "Entrar"}</h1>
      <p style={{ color: "var(--ink-2)", marginTop: 0 }}>
        {forgot
          ? "Digite seu e-mail. Enviaremos um link para você criar uma nova senha."
          : "Use o e-mail e a senha do seu cadastro."}
      </p>
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
        {sent && (
          <p role="status">
            Pronto! Se este e-mail estiver cadastrado, você receberá em instantes as instruções.
            Olhe também a caixa de spam.
          </p>
        )}
        <button type="submit" disabled={pending}>
          {forgot ? "Enviar link por e-mail" : "Entrar"}
        </button>
        <button
          type="button"
          className="plain"
          onClick={() => {
            setForgot(!forgot);
            setSent(false);
          }}
        >
          {forgot ? "Voltar para a tela de entrada" : "Esqueci minha senha"}
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
      <h1>Confirme que é você</h1>
      <p style={{ color: "var(--ink-2)", marginTop: 0 }}>
        Abra o aplicativo de códigos no seu celular e digite o número de 6 dígitos que aparece lá.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(() => session.confirmMfa(code));
        }}
      >
        <label className="field">
          Código de 6 dígitos (ou código de emergência)
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
          Entrar com outra conta
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
