import { ApiError, request, resetCsrf } from "./http";

export type Role = "company_admin" | "manager" | "employee";

export const ROLE_LABELS: Record<Role, string> = {
  company_admin: "Administrador da empresa",
  manager: "Gestor",
  employee: "Funcionário",
};

export interface Me {
  id: number;
  email: string;
  name: string;
  is_platform_admin: boolean;
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

export async function login(email: string, password: string): Promise<Me> {
  const me = await request<Me>("POST", "/api/auth/login/", { email, password });
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
    if (error.status === 429) return "Muitas tentativas. Aguarde alguns minutos.";
    if (error.status === 403) {
      // 403 também ocorre por falha de CSRF (token/origem): não confundir com falta de permissão.
      if (typeof error.body.detail === "string" && error.body.detail.startsWith("CSRF")) {
        return "Falha de segurança da requisição (CSRF). Recarregue a página e tente de novo.";
      }
      return "Você não tem permissão para esta operação.";
    }
    if (typeof error.body.detail === "string") return error.body.detail;
    const first = Object.values(error.body).flat()[0];
    if (typeof first === "string") return first;
  }
  return "Não foi possível concluir a operação.";
}
