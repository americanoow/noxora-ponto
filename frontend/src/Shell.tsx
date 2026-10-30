import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { listRequests } from "./api/attendance";
import { listMyClosings } from "./api/operational";
import { ROLE_LABELS } from "./auth";
import { useObservable } from "./lib/observable";
import { type Destination, Router, RouterContext, type ScreenName } from "./lib/router";
import { type CompanyContext, CompanyCtx, useSession } from "./lib/session";
import { useAction, useTask } from "./lib/task";
import { Icon, type IconName } from "./ui/icons";
import { Brand } from "./ui/Brand";
import { ScreenView } from "./features/screens";

interface NavItem {
  screen: ScreenName;
  label: string;
  icon: IconName;
  count?: number;
}
export interface NavGroup {
  title: string;
  items: NavItem[];
}

/** Navegação por grupos de tarefa. Itens de configuração só aparecem para quem pode usá-los. */
export function navFor(
  company: CompanyContext | null,
  isPlatform: boolean,
  linked: boolean,
  pending: number,
): NavGroup[] {
  const groups: NavGroup[] = [];
  if (company && (company.isAdmin || company.isManager)) {
    groups.push(
      {
        title: "Dia a dia",
        items: [
          { screen: "today", label: "Hoje", icon: "today" },
          { screen: "availability", label: "Situação da equipe", icon: "pulse" },
          { screen: "requests", label: "Solicitações", icon: "inbox", count: pending || undefined },
        ],
      },
      {
        title: "Jornada",
        items: [
          { screen: "records", label: "Registros de ponto", icon: "list" },
          { screen: "timesheet", label: "Folhas de ponto", icon: "sheet" },
          { screen: "closings", label: "Fechamento", icon: "lock" },
          { screen: "reports", label: "Relatórios e arquivos", icon: "doc" },
        ],
      },
      {
        title: "Equipe",
        items: [
          { screen: "employees", label: "Funcionários", icon: "people" },
          { screen: "structure", label: "Unidades e setores", icon: "building" },
          { screen: "schedules", label: "Horários de trabalho", icon: "calendar" },
        ],
      },
    );
    const settings: NavItem[] = [{ screen: "devices", label: "Tablets de ponto", icon: "tablet" }];
    if (company.isAdmin)
      settings.push(
        { screen: "rules", label: "Regras e feriados", icon: "scale" },
        { screen: "members", label: "Acessos", icon: "key" },
        { screen: "company", label: "Empresa", icon: "shield" },
        { screen: "billing", label: "Plano e pagamentos", icon: "card" },
      );
    groups.push({ title: "Configurações", items: settings });
  }
  if (company && (linked || company.role === "employee")) {
    groups.push({
      title: "Meu ponto",
      items: [
        { screen: "my-day", label: "Hoje", icon: "today" },
        { screen: "my-timesheet", label: "Minha folha de ponto", icon: "sheet" },
        { screen: "my-requests", label: "Minhas solicitações", icon: "inbox" },
        { screen: "my-closings", label: "Meses fechados", icon: "lock" },
      ],
    });
  }
  if (isPlatform)
    groups.push({
      title: "Noxora",
      items: [{ screen: "platform", label: "Empresas e assinaturas", icon: "grid" }],
    });
  return groups;
}

export function Shell() {
  const session = useSession();
  const me = useObservable(session, (s) => s.me)!;
  const companyId = useObservable(session, (s) => s.companyId);
  const membership = me.memberships.find((m) => m.company_id === companyId) ?? null;
  const company: CompanyContext | null = membership
    ? {
        companyId: membership.company_id,
        companyName: membership.company_name,
        role: membership.role,
        isAdmin: membership.role === "company_admin",
        isManager: membership.role === "manager",
      }
    : null;
  // Uma pilha de navegação por empresa/papel: trocar de empresa volta à raiz.
  return (
    <CompanyCtx.Provider value={company}>
      <CompanyShell key={`${companyId ?? "none"}:${membership?.role ?? ""}`} company={company} />
    </CompanyCtx.Provider>
  );
}

function initials(text: string): string {
  const parts = text.split(/[\s@._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "•";
}

const SHORT: Record<string, string> = {
  "Minha folha de ponto": "Folha",
  "Minhas solicitações": "Pedidos",
  "Meses fechados": "Meses",
};

function CompanyShell({ company }: { company: CompanyContext | null }) {
  const session = useSession();
  const me = useObservable(session, (s) => s.me)!;
  const staff = !!company && (company.isAdmin || company.isManager);

  const linked = useTask(
    async () => (company && staff ? (await listMyClosings(company.companyId), true) : false),
    [company?.companyId, staff],
  );
  const pending = useTask(
    async () => (company && staff ? (await listRequests(company.companyId, "pending")).length : 0),
    [company?.companyId, staff],
  );
  const groups = useMemo(
    () => navFor(company, me.is_platform_admin, linked.data === true, pending.data ?? 0),
    [company, me.is_platform_admin, linked.data, pending.data],
  );
  const allowed = useMemo(() => {
    const names = new Set<string>(groups.flatMap((g) => g.items.map((i) => i.screen)));
    names.add("account");
    if (staff) ["closing", "employee"].forEach((n) => names.add(n));
    return names;
  }, [groups, staff]);
  // "Hoje" é a página inicial do gestor; o funcionário abre direto no próprio dia.
  const rootScreen: ScreenName = staff
    ? "today"
    : company?.role === "employee"
      ? "my-day"
      : me.is_platform_admin
        ? "platform"
        : "account";
  const root = useMemo(() => ({ screen: rootScreen }) as Destination, [rootScreen]);
  const [router] = useState(() => new Router(root, (s) => allowed.has(s)));
  const path = useObservable(router, (s) => s.path);
  const top = path[path.length - 1];
  const [drawer, setDrawer] = useState(false);
  const signOut = useAction();

  useEffect(() => router.attach(), [router]);

  // A pilha pode ter vindo do endereço com uma tela não permitida para este papel.
  useEffect(() => {
    if (!allowed.has(top.screen)) router.select(root);
  }, [allowed, top.screen, router, root]);

  const go = useCallback(
    (screen: ScreenName) => {
      router.select({ screen } as Destination);
      setDrawer(false);
    },
    [router],
  );
  const current = path[0]?.screen;
  const portal = groups.find((g) => g.title === "Meu ponto");
  const employeeOnly = !staff && !!portal;
  const name = me.name || me.email;

  return (
    <RouterContext.Provider value={router}>
      <div className="window">
        <header className="mobile-bar">
          <button
            className="plain"
            aria-label="Abrir menu"
            aria-expanded={drawer}
            onClick={() => setDrawer(true)}
          >
            <Icon name="menu" size={22} />
          </button>
          <Brand />
        </header>
        {drawer && <div className="scrim" onClick={() => setDrawer(false)} aria-hidden="true" />}
        <aside className="sidebar" data-open={drawer} aria-label="Barra lateral">
          <Brand />
          <div className="company-switch">
            <span className="label">Empresa</span>
            {me.memberships.length > 1 ? (
              <select
                aria-label="Trocar de empresa"
                value={company?.companyId ?? ""}
                onChange={(e) => session.selectCompany(Number(e.target.value))}
              >
                {me.memberships.map((m) => (
                  <option key={m.id} value={m.company_id}>
                    {m.company_name}
                  </option>
                ))}
              </select>
            ) : (
              <strong>{company?.companyName ?? "Plataforma Noxora"}</strong>
            )}
          </div>
          <nav className="sidenav" aria-label="Menu principal">
            {groups.map((g) => (
              <div className="nav-group" key={g.title}>
                <h2>
                  <span className="dot deco" aria-hidden="true" />
                  {g.title}
                </h2>
                {g.items.map((item) => (
                  <button
                    key={item.screen}
                    className="nav-item"
                    aria-current={current === item.screen ? "page" : undefined}
                    onClick={() => go(item.screen)}
                  >
                    <Icon name={item.icon} />
                    {item.label}
                    {item.count !== undefined && <span className="count">{item.count}</span>}
                  </button>
                ))}
              </div>
            ))}
          </nav>
          <div className="account">
            <div className="who">
              <span className="avatar" aria-hidden="true">
                {initials(name)}
              </span>
              <span>
                <b>{me.email}</b>
                <small>{company ? ROLE_LABELS[company.role] : "Equipe Noxora"}</small>
              </span>
            </div>
            <div className="links">
              <button className="plain" onClick={() => go("account")}>
                Minha conta
              </button>
              <button
                className="plain"
                disabled={signOut.pending}
                onClick={() => void signOut.run(session.signOut)}
              >
                Sair
              </button>
            </div>
            {signOut.error && <p role="alert">{signOut.error}</p>}
          </div>
        </aside>
        <main className="content">
          {!company && !me.is_platform_admin ? (
            <NoCompany />
          ) : (
            <ScreenView destination={top} refreshPending={pending.reload} />
          )}
        </main>
        {employeeOnly && (
          <nav className="bottom-nav" aria-label="Atalhos">
            {portal.items.map((item) => (
              <button
                key={item.screen}
                aria-current={current === item.screen ? "page" : undefined}
                onClick={() => go(item.screen)}
              >
                <Icon name={item.icon} size={20} />
                {SHORT[item.label] ?? item.label}
              </button>
            ))}
          </nav>
        )}
      </div>
    </RouterContext.Provider>
  );
}

function NoCompany(): ReactNode {
  return (
    <div className="screen">
      <div className="empty" style={{ marginTop: 80 }}>
        <h3>Sua conta ainda não está ligada a nenhuma empresa.</h3>
        <p>Peça ao responsável da sua empresa para enviar um convite para o seu e-mail.</p>
      </div>
    </div>
  );
}
