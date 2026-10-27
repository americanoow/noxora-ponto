import { createContext, useContext } from "react";
import { Observable } from "./observable";

/** Destinos tipados (como `enum Destination: Hashable` + `NavigationStack`). */
export type Destination =
  | { screen: "today" }
  | { screen: "timesheet"; employeeId?: number; from?: string; to?: string }
  | { screen: "requests" }
  | { screen: "closings" }
  | { screen: "closing"; id: number }
  | { screen: "availability" }
  | { screen: "records" }
  | { screen: "employees" }
  | { screen: "employee"; id: number }
  | { screen: "structure" }
  | { screen: "schedules" }
  | { screen: "devices" }
  | { screen: "rules" }
  | { screen: "reports" }
  | { screen: "company" }
  | { screen: "members" }
  | { screen: "billing" }
  | { screen: "account" }
  | { screen: "my-day" }
  | { screen: "my-timesheet" }
  | { screen: "my-requests" }
  | { screen: "my-closings" }
  | { screen: "platform" };

export type ScreenName = Destination["screen"];

const NUMERIC = new Set(["employeeId", "id"]);

export function encode(path: Destination[]): string {
  return path
    .map((d) => {
      const params = new URLSearchParams();
      for (const [k, v] of Object.entries(d))
        if (k !== "screen" && v !== undefined) params.set(k, String(v));
      const q = params.toString();
      return q ? `${d.screen}?${q}` : d.screen;
    })
    .join("/");
}

export function decode(hash: string, valid: (s: string) => boolean): Destination[] {
  const raw = hash.replace(/^#\/?/, "");
  if (!raw) return [];
  const out: Destination[] = [];
  for (const part of raw.split("/")) {
    const [screen, query = ""] = part.split("?");
    if (!valid(screen)) return out;
    const d: Record<string, unknown> = { screen };
    for (const [k, v] of new URLSearchParams(query)) d[k] = NUMERIC.has(k) ? Number(v) : v;
    out.push(d as Destination);
  }
  return out;
}

/** Pilha de navegação: a raiz é a seção da barra lateral; `push` empilha detalhes; `pop` volta. */
export class Router extends Observable<{ path: Destination[] }> {
  constructor(
    private root: Destination,
    private isValid: (s: string) => boolean = () => true,
  ) {
    const initial = typeof window !== "undefined" ? decode(window.location.hash, isValid) : [];
    super({ path: initial.length ? initial : [root] });
  }

  /** Sincroniza com o histórico do navegador (Voltar/Avançar e links diretos). Devolve o cancelamento. */
  attach(): () => void {
    const sync = () => {
      const path = decode(window.location.hash, this.isValid);
      this.set({ path: path.length ? path : [this.root] });
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("hashchange", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("hashchange", sync);
    };
  }

  get top(): Destination {
    return this.state.path[this.state.path.length - 1];
  }

  private commit(path: Destination[]) {
    this.set({ path });
    if (typeof window !== "undefined") {
      const hash = `#/${encode(path)}`;
      if (window.location.hash !== hash) window.history.replaceState(null, "", hash);
    }
  }

  /** Troca a seção (raiz) e limpa a pilha. */
  select = (d: Destination) => this.commit([d]);
  push = (d: Destination) => this.commit([...this.state.path, d]);
  pop = () =>
    this.commit(this.state.path.length > 1 ? this.state.path.slice(0, -1) : this.state.path);
  /** Atualiza parâmetros do destino atual (filtros) sem empilhar. */
  replaceTop = (d: Destination) => this.commit([...this.state.path.slice(0, -1), d]);
  popToRoot = () => this.commit([this.state.path[0] ?? this.root]);
}

export const RouterContext = createContext<Router | null>(null);

export function useRouter(): Router {
  const router = useContext(RouterContext);
  if (!router) throw new Error("RouterContext ausente");
  return router;
}
