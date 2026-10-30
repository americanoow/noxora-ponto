import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { countRequests } from "./api/attendance";
import { getAvailabilitySettings, listMyClosings } from "./api/operational";
import { ROLE_LABELS } from "./auth";
import { useObservable } from "./lib/observable";
import { type Destination, Router, RouterContext, type ScreenName } from "./lib/router";
import { ModulesCtx } from "./lib/modules";
import { type CompanyContext, CompanyCtx, useSession } from "./lib/session";
import { useAction, useTask } from "./lib/task";
import { Icon, type IconName } from "./ui/icons";
import { Brand } from "./ui/Brand";
import { SectionTabs } from "./ui/SectionTabs";
import { ScreenView } from "./features/screens";

const ACCOUNT = "__conta";

export interface NavItem {
  screen: ScreenName;
  label: string;
  icon: IconName;
  count?: number;
  /** Telas irmãs da mesma entrada, mostradas como abas. */
  tabs?: [ScreenName, string][];
}
export interface NavGroup {
  title: string;
  items: NavItem[];
}

/** Telas que um item cobre: a principal e as abas irmãs. */
export const itemScreens = (item: NavItem): ScreenName[] =>
  item.tabs ? item.tabs.map(([screen]) => screen) : [item.screen];

const single = (item: NavItem): NavGroup => ({ title: item.label, items: [item] });

/**
 * Menu enxuto: Hoje, Ponto, Solicitações, Equipe, Fechamento e Configurações (o único com lista).
 * Telas parecidas viram abas dentro da mesma entrada. Itens de configuração só aparecem para quem
 * pode usá-los, e a situação da equipe só aparece se a empresa ativou esse módulo.
 */
export function navFor(
  company: CompanyContext | null,
  isPlatform: boolean,
  linked: boolean,
  pending: number,
  modules: { availability: boolean } = { availability: false },
): NavGroup[] {
  const groups: NavGroup[] = [];
  if (company && (company.isAdmin || company.isManager)) {
    groups.push(
      single({ screen: "today", label: "Hoje", icon: "today" }),
      single({
        screen: "timesheet",
        label: "Ponto",
        icon: "sheet",
        tabs: [
          ["timesheet", "Folha de ponto"],
          ["records", "Registros originais"],
          ["reports", "Relatórios e arquivos"],
        ],
      }),
      single({
        screen: "requests",
        label: "Solicitações",
        icon: "inbox",
        count: pending || undefined,
      }),
      single({
        screen: "employees",
        label: "Equipe",
        icon: "people",
        tabs: modules.availability
          ? [
              ["employees", "Funcionários"],
              ["availability", "Situação da equipe"],
            ]
          : undefined,
      }),
      single({ screen: "closings", label: "Fechamento", icon: "lock" }),
    );
    const settings: NavItem[] = [
      {
        screen: "structure",
        label: "Jornada",
        icon: "calendar",
        tabs: [
          ["structure", "Unidades e setores"],
          ["schedules", "Horários de trabalho"],
          ...(company.isAdmin ? ([["rules", "Regras e feriados"]] as [ScreenName, string][]) : []),
        ],
      },
      { screen: "devices", label: "Tablets de ponto", icon: "tablet" },
    ];
    if (company.isAdmin)
      settings.push(
        { screen: "members", label: "Acessos", icon: "key" },
        {
          screen: "company",
          label: "Empresa e plano",
          icon: "shield",
          tabs: [
            ["company", "Dados da empresa"],
            ["billing", "Plano e pagamentos"],
          ],
        },
      );
    groups.push({ title: "Configurações", items: settings });
  }
  const mine: NavItem[] = [
    { screen: "my-day", label: "Hoje", icon: "today" },
    { screen: "my-timesheet", label: "Minha folha de ponto", icon: "sheet" },
    { screen: "my-requests", label: "Minhas solicitações", icon: "inbox" },
  ];
  if (company && linked) groups.push({ title: "Meu ponto", items: mine });
  else if (company && company.role === "employee") groups.push(...mine.map(single));
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
    async () =>
      company && staff ? await countRequests(company.companyId, { status: "pending" }) : 0,
    [company?.companyId, staff],
  );
  // Módulo opcional: se a leitura falhar, o módulo é tratado como desligado.
  const availability = useTask(
    async () =>
      company
        ? (await getAvailabilitySettings(company.companyId).catch(() => null))?.enabled === true
        : false,
    [company?.companyId],
  );
  const modules = useMemo(
    () => ({ availability: availability.data === true, reload: availability.reload }),
    [availability.data, availability.reload],
  );
  const groups = useMemo(
    () => navFor(company, me.is_platform_admin, linked.data === true, pending.data ?? 0, modules),
    [company, me.is_platform_admin, linked.data, pending.data, modules],
  );
  const allowed = useMemo(() => {
    const names = new Set<string>(groups.flatMap((g) => g.items.flatMap(itemScreens)));
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
  const [openMenu, setOpenMenu] = useState<string | null>(null);
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
      setOpenMenu(null);
    },
    [router],
  );
  const current = path[0]?.screen;
  const portalScreens = new Set<ScreenName>(["my-day", "my-timesheet", "my-requests"]);
  const portal = groups.flatMap((g) => g.items).filter((i) => portalScreens.has(i.screen));
  const employeeOnly = !staff && portal.length > 0;
  const tabs =
    groups
      .flatMap((g) => g.items)
      .find((i) => i.tabs && i.tabs.length > 1 && itemScreens(i).includes(top.screen))?.tabs ??
    null;
  const name = me.name || me.email;

  return (
    <RouterContext.Provider value={router}>
      <ModulesCtx.Provider value={modules}>
        <div className="window">
          <header className="topbar" data-open={drawer}>
            <button className="brand-link" aria-label="Ir para Hoje" onClick={() => go(rootScreen)}>
              <Brand />
            </button>
            <button
              className="plain hamburger"
              aria-label={drawer ? "Fechar menu" : "Abrir menu"}
              aria-expanded={drawer}
              onClick={() => setDrawer(!drawer)}
            >
              <Icon name={drawer ? "x" : "menu"} size={24} />
            </button>
            <div className="topcollapse">
              <nav className="topnav" aria-label="Menu principal">
                {groups.map((g) => {
                  const active = g.items.some((i) => itemScreens(i).includes(current));
                  const open = openMenu === g.title;
                  if (g.items.length === 1) {
                    const item = g.items[0];
                    return (
                      <div key={g.title} className="menu">
                        <button
                          className="menu-trigger"
                          aria-current={active ? "page" : undefined}
                          onClick={() => go(item.screen)}
                        >
                          {g.title}
                          {item.count !== undefined && <span className="pip" aria-hidden="true" />}
                        </button>
                      </div>
                    );
                  }
                  return (
                    <div
                      key={g.title}
                      className="menu"
                      data-open={open}
                      onMouseEnter={() => setOpenMenu(g.title)}
                      onMouseLeave={() => setOpenMenu((o) => (o === g.title ? null : o))}
                      onBlur={(e) => {
                        if (!e.currentTarget.contains(e.relatedTarget as Node | null))
                          setOpenMenu((o) => (o === g.title ? null : o));
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Escape") setOpenMenu(null);
                      }}
                    >
                      <button
                        className="menu-trigger"
                        aria-haspopup="true"
                        aria-expanded={open}
                        aria-current={active ? "true" : undefined}
                        onClick={(e) => setOpenMenu(open && e.detail === 0 ? null : g.title)}
                      >
                        {g.title}
                        {g.items.some((i) => i.count) && (
                          <span className="pip" aria-hidden="true" />
                        )}
                        <span className="caret" aria-hidden="true" />
                      </button>
                      <div className="menu-panel">
                        {g.items.map((item) => (
                          <button
                            key={item.screen}
                            className="nav-item"
                            aria-current={itemScreens(item).includes(current) ? "page" : undefined}
                            onClick={() => go(item.screen)}
                          >
                            <Icon name={item.icon} />
                            {item.label}
                            {item.count !== undefined && (
                              <span className="count">{item.count}</span>
                            )}
                          </button>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </nav>
              <div className="topbar-end">
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
                  <span className="company-name">
                    {company?.companyName ?? "Plataforma Noxora"}
                  </span>
                )}
                <div
                  className="menu menu-right"
                  data-open={openMenu === ACCOUNT}
                  onMouseEnter={() => setOpenMenu(ACCOUNT)}
                  onMouseLeave={() => setOpenMenu((o) => (o === ACCOUNT ? null : o))}
                  onBlur={(e) => {
                    if (!e.currentTarget.contains(e.relatedTarget as Node | null))
                      setOpenMenu((o) => (o === ACCOUNT ? null : o));
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") setOpenMenu(null);
                  }}
                >
                  <button
                    className="menu-trigger"
                    aria-haspopup="true"
                    aria-expanded={openMenu === ACCOUNT}
                    onClick={(e) =>
                      setOpenMenu(openMenu === ACCOUNT && e.detail === 0 ? null : ACCOUNT)
                    }
                  >
                    <span className="avatar" aria-hidden="true">
                      {initials(name)}
                    </span>
                    <span className="who-email">{me.email}</span>
                    <span className="caret" aria-hidden="true" />
                  </button>
                  <div className="menu-panel account-panel">
                    <div className="who">
                      <b>{me.email}</b>
                      <small>
                        {company
                          ? `${company.companyName} · ${ROLE_LABELS[company.role]}`
                          : "Equipe Noxora"}
                      </small>
                    </div>
                    <button className="nav-item" onClick={() => go("account")}>
                      <Icon name="person" /> Minha conta
                    </button>
                    <button
                      className="nav-item"
                      disabled={signOut.pending}
                      onClick={() => void signOut.run(session.signOut)}
                    >
                      <Icon name="x" /> Sair
                    </button>
                    {signOut.error && <p role="alert">{signOut.error}</p>}
                  </div>
                </div>
              </div>
            </div>
          </header>
          {drawer && <div className="scrim" onClick={() => setDrawer(false)} aria-hidden="true" />}
          <main className="content">
            {!company && !me.is_platform_admin ? (
              <NoCompany />
            ) : (
              <>
                {tabs && <SectionTabs tabs={tabs} current={top.screen} />}
                <ScreenView destination={top} refreshPending={pending.reload} />
              </>
            )}
          </main>
          {employeeOnly && (
            <nav className="bottom-nav" aria-label="Atalhos">
              {portal.map((item) => (
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
      </ModulesCtx.Provider>
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
