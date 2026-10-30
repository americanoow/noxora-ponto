import { ApiError, request, resetCsrf } from "./http";

export type Role = "company_admin" | "manager" | "employee";

export const ROLE_LABELS: Record<Role, string> = {
  company_admin: "Administrador (acessa tudo)",
  manager: "Gestor (cuida de uma equipe)",
  employee: "Funcionário (vê só o próprio ponto)",
};

export interface Me {
  id: number;
  email: string;
  name: string;
  is_platform_admin: boolean;
  mfa_enabled?: boolean;
  memberships: { id: number; company_id: number; company_name: string; role: Role }[];
}

export interface Member {
  id: number;
  email: string;
  name: string;
  role: Role;
  is_active: boolean;
}

export interface Company {
  id: number;
  name: string;
  is_active: boolean;
}

export async function fetchMe(): Promise<Me | null> {
  try {
    return await request<Me>("GET", "/api/auth/me/");
  } catch (error) {
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) return null;
    throw error;
  }
}

export interface MfaChallenge {
  mfa_required: true;
}

export function isMfaChallenge(value: Me | MfaChallenge): value is MfaChallenge {
  return (value as MfaChallenge).mfa_required === true;
}

/** Login. Com segundo fator ativo, devolve o desafio; a sessão só nasce em `verifyMfa`. */
export async function login(email: string, password: string): Promise<Me | MfaChallenge> {
  const result = await request<Me | MfaChallenge>("POST", "/api/auth/login/", { email, password });
  resetCsrf();
  return result;
}

export async function verifyMfa(code: string): Promise<Me> {
  const me = await request<Me>("POST", "/api/auth/mfa/verify/", { code });
  resetCsrf();
  return me;
}

export async function logout(): Promise<void> {
  await request<void>("POST", "/api/auth/logout/");
  resetCsrf();
}

export const requestPasswordReset = (email: string) =>
  request<void>("POST", "/api/auth/password-reset/", { email });

export const confirmPasswordReset = (uid: string, token: string, newPassword: string) =>
  request<void>("POST", "/api/auth/password-reset/confirm/", {
    uid,
    token,
    new_password: newPassword,
  });

export const listMembers = (companyId: number) =>
  request<Member[]>("GET", `/api/companies/${companyId}/members/`);

export const addMember = (companyId: number, email: string, name: string, role: Role) =>
  request<Member>("POST", `/api/companies/${companyId}/members/`, { email, name, role });

export const updateMember = (
  companyId: number,
  memberId: number,
  changes: Partial<Pick<Member, "role" | "is_active">>,
) => request<Member>("PATCH", `/api/companies/${companyId}/members/${memberId}/`, changes);

export const listCompanies = () => request<Company[]>("GET", "/api/companies/");

export const createCompany = (name: string, adminEmail: string) =>
  request<Company>("POST", "/api/companies/", { name, admin_email: adminEmail });

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429)
      return "Você tentou muitas vezes seguidas. Aguarde alguns minutos e tente de novo.";
    if (error.status === 401) return "Sua sessão acabou. Entre de novo para continuar.";
    if (error.status === 404) return "Não encontramos o que você procurou. Pode ter sido removido.";
    if (error.status >= 500)
      return "O sistema está com problemas no momento. Tente de novo em instantes.";
    if (error.status === 403) {
      // 403 também ocorre por falha de CSRF (token/origem): não confundir com falta de permissão.
      if (typeof error.body.detail === "string" && error.body.detail.startsWith("CSRF")) {
        return "Por segurança, esta página precisa ser recarregada. Atualize a página (tecla F5) e tente de novo.";
      }
      return "Você não tem permissão para fazer isto. Fale com o administrador da sua empresa.";
    }
    if (typeof error.body.detail === "string") return error.body.detail;
    const first = Object.values(error.body).flat()[0];
    if (typeof first === "string") return first;
  }
  if (error instanceof TypeError)
    return "Não conseguimos falar com o sistema. Verifique sua internet e tente de novo.";
  return "Não foi possível concluir. Tente de novo; se continuar, fale com o suporte.";
}
