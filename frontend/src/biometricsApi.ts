import { request } from "./http";

export interface BiometricStatus {
  employee_id: number;
  consent: { policy_version: string; granted_at: string } | null;
  template: {
    engine: string;
    engine_version: string;
    created_at: string;
    quality: number | null;
  } | null;
  engine: { name: string; version: string; simulator: boolean } | null;
}

export interface ExceptionGrant {
  authorization_id: number;
  /** Código de 8 dígitos exibido uma única vez. */
  code: string;
  expires_at: string;
}

export type IdentificationMode = "registration" | "face";

const emp = (c: number, e: number) => `/api/companies/${c}/employees/${e}`;

export const getBiometricStatus = (c: number, e: number) =>
  request<BiometricStatus>("GET", `${emp(c, e)}/biometric/`);
export const grantConsent = (c: number, e: number, policyVersion: string, evidenceRef: string) =>
  request<BiometricStatus>("POST", `${emp(c, e)}/biometric/consent/`, {
    policy_version: policyVersion,
    evidence_ref: evidenceRef,
  });
export const revokeConsent = (c: number, e: number) =>
  request<BiometricStatus>("DELETE", `${emp(c, e)}/biometric/consent/`);
export const enrollFace = (c: number, e: number, images: string[]) =>
  request<BiometricStatus>("POST", `${emp(c, e)}/biometric/enroll/`, { images });
export const deleteTemplate = (c: number, e: number) =>
  request<BiometricStatus>("DELETE", `${emp(c, e)}/biometric/`);
export const authorizeException = (c: number, e: number, reason: string) =>
  request<ExceptionGrant>("POST", `${emp(c, e)}/identification-exceptions/`, { reason });

export type OfflinePolicy = "disabled" | "registration_only";
export interface IdentificationPolicy {
  mode: IdentificationMode;
  offline_policy: OfflinePolicy;
}

export const getIdentificationMode = (c: number) =>
  request<IdentificationPolicy>("GET", `/api/companies/${c}/identification/`);
export const setIdentificationPolicy = (c: number, changes: Partial<IdentificationPolicy>) =>
  request<IdentificationPolicy>("PATCH", `/api/companies/${c}/identification/`, changes);

/** Lê o arquivo como base64 SEM o prefixo data:. A imagem não é guardada em nenhum armazenamento do navegador. */
export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Não foi possível ler o arquivo."));
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.readAsDataURL(file);
  });
}
