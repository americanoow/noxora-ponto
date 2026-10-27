import { useCallback, useEffect, useState } from "react";
import {
  type Company,
  type Member,
  ROLE_LABELS,
  type Role,
  addMember,
  confirmPasswordReset,
  createCompany,
  errorMessage,
  listCompanies,
  listMembers,
  updateMember,
} from "./auth";

function useAction() {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return { error, busy, run };
}

const Error_ = ({ message }: { message: string | null }) =>
  message ? <p role="alert">{message}</p> : null;

export function ResetPasswordScreen({ uid, token }: { uid: string; token: string }) {
  const { error, busy, run } = useAction();
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);

  if (done) return <p role="status">Senha atualizada. Você já pode entrar.</p>;
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void run(async () => {
          await confirmPasswordReset(uid, token, password);
          setDone(true);
        });
      }}
    >
      <h2>Definir nova senha</h2>
      <label>
        Nova senha (mínimo de 10 caracteres)
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          minLength={10}
          required
        />
      </label>
      <Error_ message={error} />
      <button type="submit" disabled={busy}>
        Salvar senha
      </button>
    </form>
  );
}

export function MembersPanel({ companyId, myRole }: { companyId: number; myRole: Role }) {
  const { error, run } = useAction();
  const [members, setMembers] = useState<Member[] | null>(null);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("employee");
  const isAdmin = myRole === "company_admin";

  const load = useCallback(
    () =>
      run(async () => {
        setMembers(await listMembers(companyId));
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [companyId],
  );
  useEffect(() => {
    if (isAdmin) void load();
  }, [isAdmin, load]);

  if (!isAdmin) return <p>Somente administradores da empresa gerenciam acessos.</p>;

  return (
    <section>
      <h3>Acessos da empresa</h3>
      <Error_ message={error} />
      <ul>
        {members?.map((m) => (
          <li key={m.id}>
            {m.name || m.email} ({m.email}) — {ROLE_LABELS[m.role]}
            {m.is_active ? "" : " [inativo]"}{" "}
            <select
              aria-label={`Papel de ${m.email}`}
              value={m.role}
              onChange={(e) =>
                void run(async () => {
                  await updateMember(companyId, m.id, { role: e.target.value as Role });
                  await load();
                })
              }
            >
              {(Object.keys(ROLE_LABELS) as Role[]).map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABELS[r]}
                </option>
              ))}
            </select>
            <button
              onClick={() =>
                void run(async () => {
                  await updateMember(companyId, m.id, { is_active: !m.is_active });
                  await load();
                })
              }
            >
              {m.is_active ? "Desativar" : "Reativar"}
            </button>
          </li>
        ))}
      </ul>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            await addMember(companyId, email, name, role);
            setEmail("");
            setName("");
            await load();
          });
        }}
      >
        <h4>Convidar usuário</h4>
        <input
          aria-label="E-mail do convidado"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <input
          aria-label="Nome do convidado"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <select
          aria-label="Papel do convidado"
          value={role}
          onChange={(e) => setRole(e.target.value as Role)}
        >
          {(Object.keys(ROLE_LABELS) as Role[]).map((r) => (
            <option key={r} value={r}>
              {ROLE_LABELS[r]}
            </option>
          ))}
        </select>
        <button type="submit">Convidar</button>
      </form>
    </section>
  );
}

export function PlatformPanel() {
  const { error, run } = useAction();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [name, setName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");

  const load = useCallback(
    () =>
      run(async () => {
        setCompanies(await listCompanies());
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section>
      <h3>Empresas clientes</h3>
      <Error_ message={error} />
      <ul>
        {companies.map((c) => (
          <li key={c.id}>
            {c.name}
            {c.is_active ? "" : " [inativa]"}
          </li>
        ))}
      </ul>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            await createCompany(name, adminEmail);
            setName("");
            setAdminEmail("");
            await load();
          });
        }}
      >
        <h4>Nova empresa</h4>
        <input
          aria-label="Nome da empresa"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <input
          aria-label="E-mail do administrador"
          type="email"
          value={adminEmail}
          onChange={(e) => setAdminEmail(e.target.value)}
          required
        />
        <button type="submit">Criar empresa</button>
      </form>
    </section>
  );
}
