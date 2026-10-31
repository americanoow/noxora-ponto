import { request } from "./http";

export type DeviceStatus = "pending" | "active" | "revoked";
export type Connectivity = "online" | "stale" | "offline" | "never";

export interface Device {
  id: number;
  name: string;
  unit: number;
  unit_name: string;
  status: DeviceStatus;
  last_seen_at: string | null;
  app_version: string;
  connectivity: Connectivity;
  collect_location: boolean;
  location_justification: string;
}

/** Resposta de criação/renovação: o código de ativação só aparece nesta resposta. */
export interface DeviceWithCode extends Device {
  activation_code: string;
  activation_expires_at: string;
}

const base = (c: number) => `/api/companies/${c}/devices/`;

export const listDevices = (c: number) => request<Device[]>("GET", base(c));
export const createDevice = (c: number, name: string, unit: number) =>
  request<DeviceWithCode>("POST", base(c), { name, unit });
export const revokeDevice = (c: number, id: number) =>
  request<Device>("POST", `${base(c)}${id}/revoke/`);
export const reissueDeviceCode = (c: number, id: number) =>
  request<DeviceWithCode>("POST", `${base(c)}${id}/activation-code/`);
