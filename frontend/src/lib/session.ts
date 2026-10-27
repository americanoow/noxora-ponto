import { createContext, useContext } from "react";
import { type Me, type Role, fetchMe, isMfaChallenge, login, logout, verifyMfa } from "../auth";
import { Observable } from "./observable";

export interface SessionState {
  status: "loading" | "anonymous" | "mfa" | "ready" | "error";
  me: Me | null;
  companyId: number | null;
}

const STORAGE_KEY = "noxora.company";

function rememberedCompany(me: Me): number | null {
  let saved: number | null = null;
  try {
    saved = Number(localStorage.getItem(STORAGE_KEY)) || null;
  } catch {
    saved = null;
  }
  if (saved && me.memberships.some((m) => m.company_id === saved)) return saved;
  return me.memberships[0]?.company_id ?? null;
}

/** Sessão do usuário (modelo observável compartilhado pelo `SessionContext`). */
export class Session extends Observable<SessionState> {
  constructor() {
    super({ status: "loading", me: null, companyId: null });
  }

  private ready(me: Me) {
    this.set({ status: "ready", me, companyId: rememberedCompany(me) });
  }

  load = async () => {
    try {
      const me = await fetchMe();
      if (me) this.ready(me);
      else this.set({ status: "anonymous", me: null, companyId: null });
    } catch {
      this.set({ status: "error" });
    }
  };

  /** Lança erro (mensagem tratada pela tela) em credencial inválida. */
  signIn = async (email: string, password: string) => {
    const result = await login(email, password);
    if (isMfaChallenge(result)) this.set({ status: "mfa" });
    else this.ready(result);
  };

  confirmMfa = async (code: string) => {
    this.ready(await verifyMfa(code));
  };

  cancelMfa = () => this.set({ status: "anonymous" });

  signOut = async () => {
    await logout();
    this.set({ status: "anonymous", me: null, companyId: null });
  };

  refresh = async () => {
    const me = await fetchMe();
    if (me) this.set({ me });
  };

  selectCompany = (companyId: number) => {
    try {
      localStorage.setItem(STORAGE_KEY, String(companyId));
    } catch {
      /* armazenamento indisponível: só não lembra a escolha */
    }
    this.set({ companyId });
  };
}

export interface CompanyContext {
  companyId: number;
  companyName: string;
  role: Role;
  isAdmin: boolean;
  isManager: boolean;
}

export const SessionContext = createContext<Session | null>(null);
export const CompanyCtx = createContext<CompanyContext | null>(null);

export function useSession(): Session {
  const s = useContext(SessionContext);
  if (!s) throw new Error("SessionContext ausente");
  return s;
}

/** Empresa e papel atuais (equivalente a `@Environment(Company.self)`). */
export function useCompany(): CompanyContext {
  const c = useContext(CompanyCtx);
  if (!c) throw new Error("CompanyCtx ausente");
  return c;
}
