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

const ACCOUNT = "__conta";

interface NavItem {
  screen: ScreenName;
  label: string;
  hint: string;
  icon: IconName;
  count?: number;
}
export interface NavGroup {
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
      {
        title: "Visão geral",
        items: [
          {
            screen: "today",
            label: "Hoje",
            hint: "Quem está trabalhando agora e o que precisa da sua atenção.",
            icon: "today",
          },
        ],
      },
      {
        title: "Controle de ponto",
        items: [
          {
            screen: "timesheet",
            label: "Folha de ponto",
            hint: "Veja as horas de cada funcionário, dia a dia.",
            icon: "sheet",
          },
          {
            screen: "requests",
            label: "Pedidos",
            hint: "Aprove ou recuse correções de ponto e justificativas de ausência.",
            icon: "inbox",
            count: pending || undefined,
          },
          {
            screen: "closings",
            label: "Fechar o mês",
            hint: "Trave o período para a folha de pagamento e envie a conferência aos funcionários.",
            icon: "lock",
          },
        ],
      },
      {
        title: "Equipe e tablets",
        items: [
          {
            screen: "availability",
            label: "Situação da equipe",
            hint: "Informe e consulte quem está disponível, em pausa ou fora.",
            icon: "pulse",
          },
          {
            screen: "records",
            label: "Registros de ponto",
            hint: "Lista de todas as batidas de ponto feitas nos tablets.",
            icon: "list",
          },
          {
            screen: "devices",
            label: "Tablets de ponto",
            hint: "Cadastre e ative os tablets usados para bater o ponto.",
            icon: "tablet",
          },
        ],
      },
      {
        title: "Cadastros",
        items: [
          {
            screen: "employees",
            label: "Funcionários",
            hint: "Cadastre pessoas, mude de setor e defina o horário de trabalho.",
            icon: "people",
          },
          {
            screen: "structure",
            label: "Unidades e setores",
            hint: "Lojas, filiais e departamentos da empresa.",
            icon: "building",
          },
          {
            screen: "schedules",
            label: "Horários de trabalho",
            hint: "Defina em quais dias e horas cada pessoa deve trabalhar.",
            icon: "calendar",
          },
        ],
      },
    );
    const companyItems: NavItem[] = [
      {
        screen: "reports",
        label: "Relatórios e arquivos",
        hint: "Baixe planilhas, arquivos para a fiscalização e para a folha de pagamento.",
        icon: "doc",
      },
    ];
    if (company.isAdmin) {
      companyItems.unshift({
        screen: "rules",
        label: "Regras e feriados",
        hint: "Tolerâncias, hora extra, adicional noturno e feriados.",
        icon: "scale",
      });
      companyItems.push(
        {
          screen: "company",
          label: "Dados da empresa",
          hint: "Dados da empresa e como os funcionários se identificam no tablet.",
          icon: "shield",
        },
        {
          screen: "members",
          label: "Quem usa o sistema",
          hint: "Convide pessoas e escolha o que cada uma pode fazer.",
          icon: "key",
        },
        {
          screen: "billing",
          label: "Plano e pagamentos",
          hint: "Seu plano, uso e faturas.",
          icon: "card",
        },
      );
    }
    groups.push({ title: "Administração", items: companyItems });
  }
  if (company && (linked || company.role === "employee")) {
    groups.push({
      title: "Meu ponto",
      items: [
        {
          screen: "my-day",
          label: "Hoje",
          hint: "Suas batidas de ponto recentes e comprovantes.",
          icon: "today",
        },
        {
          screen: "my-timesheet",
          label: "Minha folha de ponto",
          hint: "Veja suas horas do mês e peça correções.",
          icon: "sheet",
        },
        {
          screen: "my-requests",
          label: "Meus pedidos",
          hint: "Acompanhe os pedidos de correção que você fez.",
          icon: "inbox",
        },
        {
          screen: "my-closings",
          label: "Meses fechados",
          hint: "Confira o mês encerrado e confirme que está correto.",
          icon: "lock",
        },
      ],
    });
  }
  if (isPlatform)
    groups.push({
      title: "Noxora",
      items: [
        {
          screen: "platform",
          label: "Plataforma",
          hint: "Empresas clientes e assinaturas.",
          icon: "grid",
        },
      ],
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
    names.add("home");
    if (staff) ["closing", "employee"].forEach((n) => names.add(n));
    return names;
  }, [groups, staff]);
  const rootScreen: ScreenName = groups.length ? "home" : "account";
  const root = useMemo(() => ({ screen: rootScreen }) as Destination, [rootScreen]);
  const [router] = useState(() => new Router(root, (s) => allowed.has(s)));
  const path = useObservable(router, (s) => s.path);
  const top = path[path.length - 1];
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const signOut = useAction();

  useEffect(() => router.attach(), [router]);

  // A pilha pode ter vindo do endereço com uma tela não permitida para este papel.
  useEffect(() => {
    if (!allowed.has(top.screen)) router.select(root);
  }, [allowed, top.screen, router, root]);

  const go = useCallback(
    (screen: ScreenName) => {
      router.select({ screen } as Destination);
      setOpenGroup(null);
    },
    [router],
  );

  return (
    <RouterContext.Provider value={router}>
      <div className="window">
        <header className="topbar">
          <div className="brand">
            <span className="brand-mark">
              <Icon name="today" size={16} />
            </span>
            Noxora Ponto
          </div>
          <nav className="topnav" aria-label="Menu principal">
            <button
              className="menu-trigger"
              aria-current={path[0]?.screen === "home" ? "page" : undefined}
              onClick={() => go("home")}
            >
              Início
            </button>
            {groups.map((g) => {
              const active = g.items.some((i) => i.screen === path[0]?.screen);
              const open = openGroup === g.title;
              return (
                <div
                  key={g.title}
                  className="menu"
                  data-open={open}
                  onMouseEnter={() => setOpenGroup(g.title)}
                  onMouseLeave={() => setOpenGroup((o) => (o === g.title ? null : o))}
                  onBlur={(e) => {
                    if (!e.currentTarget.contains(e.relatedTarget as Node | null))
                      setOpenGroup((o) => (o === g.title ? null : o));
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") setOpenGroup(null);
                  }}
                >
                  <button
                    className="menu-trigger"
                    aria-haspopup="true"
                    aria-expanded={open}
                    aria-current={active ? "true" : undefined}
                    onClick={() => setOpenGroup(open ? null : g.title)}
                  >
                    {g.title}
                    <span className="caret" aria-hidden="true" />
                  </button>
                  <div className="menu-panel">
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
                  </div>
                </div>
              );
            })}
          </nav>
          <div className="topbar-end">
            {me.memberships.length > 1 && (
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
            )}
            <div
              className="menu menu-right"
              data-open={openGroup === ACCOUNT}
              onMouseEnter={() => setOpenGroup(ACCOUNT)}
              onMouseLeave={() => setOpenGroup((o) => (o === ACCOUNT ? null : o))}
              onBlur={(e) => {
                if (!e.currentTarget.contains(e.relatedTarget as Node | null))
                  setOpenGroup((o) => (o === ACCOUNT ? null : o));
              }}
              onKeyDown={(e) => {
                if (e.key === "Escape") setOpenGroup(null);
              }}
            >
              <button
                className="menu-trigger"
                aria-haspopup="true"
                aria-expanded={openGroup === ACCOUNT}
                onClick={() => setOpenGroup(openGroup === ACCOUNT ? null : ACCOUNT)}
              >
                {me.email}
                <span className="caret" aria-hidden="true" />
              </button>
              <div className="menu-panel sidebar-footer">
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
            </div>
          </div>
        </header>
        <main className="content">
          {!company && !me.is_platform_admin ? (
            <NoCompany />
          ) : (
            <ScreenView destination={top} refreshPending={pending.reload} groups={groups} />
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
        <h3>Sua conta ainda não está ligada a nenhuma empresa.</h3>
        <p>Peça ao responsável da sua empresa para enviar um convite para o seu e-mail.</p>
      </div>
    </div>
  );
}
