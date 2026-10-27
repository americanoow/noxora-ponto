import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { listRequests } from "./api/attendance";
import { listMyClosings } from "./api/operational";
import { ROLE_LABELS } from "./auth";
import { useObservable } from "./lib/observable";
import { type Destination, Router, RouterContext, type ScreenName } from "./lib/router";
import { type CompanyContext, CompanyCtx, useSession } from "./lib/session";
import { useAction, useTask } from "./lib/task";
import { Icon, type IconName } from "./ui/icons";
import { ScreenView } from "./features/screens";

interface NavItem {
  screen: ScreenName;
  label: string;
  icon: IconName;
  count?: number;
}
interface NavGroup {
  title: string;
  items: NavItem[];
}

function navFor(
  company: CompanyContext | null,
  isPlatform: boolean,
  linked: boolean,
  pending: number,
): NavGroup[] {
  const groups: NavGroup[] = [];
  if (company && (company.isAdmin || company.isManager)) {
    groups.push(
      { title: "Visão geral", items: [{ screen: "today", label: "Hoje", icon: "today" }] },
      {
        title: "Jornada",
        items: [
          { screen: "timesheet", label: "Espelho de ponto", icon: "sheet" },
          { screen: "requests", label: "Pedidos", icon: "inbox", count: pending || undefined },
          { screen: "closings", label: "Fechamentos", icon: "lock" },
        ],
      },
      {
        title: "Operação",
        items: [
          { screen: "availability", label: "Disponibilidade", icon: "pulse" },
          { screen: "records", label: "Marcações", icon: "list" },
          { screen: "devices", label: "Tablets", icon: "tablet" },
        ],
      },
      {
        title: "Cadastros",
        items: [
          { screen: "employees", label: "Funcionários", icon: "people" },
          { screen: "structure", label: "Unidades e setores", icon: "building" },
          { screen: "schedules", label: "Jornadas", icon: "calendar" },
        ],
      },
    );
    const companyItems: NavItem[] = [
      { screen: "reports", label: "Relatórios e arquivos", icon: "doc" },
    ];
    if (company.isAdmin) {
      companyItems.unshift({ screen: "rules", label: "Regras e feriados", icon: "scale" });
      companyItems.push(
        { screen: "company", label: "Empresa e identificação", icon: "shield" },
        { screen: "members", label: "Acessos", icon: "key" },
        { screen: "billing", label: "Assinatura", icon: "card" },
      );
    }
    groups.push({ title: "Administração", items: companyItems });
  }
  if (company && (linked || company.role === "employee")) {
    groups.push({
      title: "Meu ponto",
      items: [
        { screen: "my-day", label: "Hoje", icon: "today" },
        { screen: "my-timesheet", label: "Meu espelho", icon: "sheet" },
        { screen: "my-requests", label: "Meus pedidos", icon: "inbox" },
        { screen: "my-closings", label: "Períodos fechados", icon: "lock" },
      ],
    });
  }
  if (isPlatform)
    groups.push({
      title: "Noxora",
      items: [{ screen: "platform", label: "Plataforma", icon: "grid" }],
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
  const rootScreen = groups[0]?.items[0]?.screen ?? "account";
  const root = useMemo(() => ({ screen: rootScreen }) as Destination, [rootScreen]);
  const [router] = useState(() => new Router(root, (s) => allowed.has(s)));
  const path = useObservable(router, (s) => s.path);
  const top = path[path.length - 1];
  const [menuOpen, setMenuOpen] = useState(false);
  const signOut = useAction();

  useEffect(() => router.attach(), [router]);

  // A pilha pode ter vindo do endereço com uma tela não permitida para este papel.
  useEffect(() => {
    if (!allowed.has(top.screen)) router.select(root);
  }, [allowed, top.screen, router, root]);

  const go = useCallback(
    (screen: ScreenName) => {
      router.select({ screen } as Destination);
      setMenuOpen(false);
    },
    [router],
  );

  return (
    <RouterContext.Provider value={router}>
      <div className={menuOpen ? "window menu-open" : "window"}>
        <aside className="sidebar" aria-label="Navegação">
          <div className="brand">
            <span className="brand-mark">
              <Icon name="today" size={16} />
            </span>
            Noxora Ponto
          </div>
          {me.memberships.length > 1 && (
            <div className="company-picker">
              <select
                aria-label="Empresa"
                value={company?.companyId ?? ""}
                onChange={(e) => session.selectCompany(Number(e.target.value))}
              >
                {me.memberships.map((m) => (
                  <option key={m.id} value={m.company_id}>
                    {m.company_name}
                  </option>
                ))}
              </select>
            </div>
          )}
          {groups.map((g) => (
            <nav key={g.title} className="nav-group" aria-label={g.title}>
              <h2>{g.title}</h2>
              {g.items.map((item) => (
                <button
                  key={item.screen}
                  className="nav-item"
                  aria-current={path[0]?.screen === item.screen ? "page" : undefined}
                  onClick={() => go(item.screen)}
                >
                  <Icon name={item.icon} />
                  {item.label}
                  {item.count !== undefined && <span className="count">{item.count}</span>}
                </button>
              ))}
            </nav>
          ))}
          <div className="sidebar-footer">
            <div>{me.email}</div>
            {company && (
              <div>
                {company.companyName} — {ROLE_LABELS[company.role]}
              </div>
            )}
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
            {signOut.error && <p role="alert">{signOut.error}</p>}
          </div>
        </aside>
        <main className="content">
          <button
            className="menu-button plain"
            aria-label="Abrir menu"
            onClick={() => setMenuOpen(true)}
            style={{ marginTop: 12 }}
          >
            <Icon name="menu" /> Menu
          </button>
          {menuOpen && <div className="scrim" onClick={() => setMenuOpen(false)} />}
          {!company && !me.is_platform_admin ? (
            <NoCompany />
          ) : (
            <ScreenView destination={top} refreshPending={pending.reload} />
          )}
        </main>
      </div>
    </RouterContext.Provider>
  );
}

function NoCompany(): ReactNode {
  return (
    <div className="screen">
      <div className="empty" style={{ marginTop: 80 }}>
        <h3>Seu usuário não possui acesso a nenhuma empresa.</h3>
        <p>Peça ao administrador da sua empresa para enviar um convite.</p>
      </div>
    </div>
  );
}
