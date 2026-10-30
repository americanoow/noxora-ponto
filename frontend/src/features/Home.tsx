import { useObservable } from "../lib/observable";
import { type Destination, useRouter } from "../lib/router";
import type { NavGroup } from "../Shell";
import { useSession } from "../lib/session";
import { Group, Row, Screen } from "../ui/kit";
import { Icon } from "../ui/icons";

/** Tela de início: atalhos para todas as funções do papel, agrupados por categoria. */
export function HomeScreen({ groups }: { groups: NavGroup[] }) {
  const session = useSession();
  const router = useRouter();
  const me = useObservable(session, (s) => s.me);
  const companyId = useObservable(session, (s) => s.companyId);
  const membership = me?.memberships.find((m) => m.company_id === companyId);
  const name = me?.name || me?.email || "";
  return (
    <Screen title="Início" subtitle={membership ? membership.company_name : "Plataforma Noxora"}>
      <p style={{ color: "var(--ink-2)", marginTop: 0 }}>Olá, {name}! O que você quer fazer?</p>
      {groups.map((g) => (
        <Group key={g.title} title={g.title}>
          {g.items.map((item) => (
            <Row
              key={item.screen}
              title={
                <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
                  <Icon name={item.icon} />
                  {item.label}
                </span>
              }
              subtitle={item.hint}
              value={item.count !== undefined ? item.count : undefined}
              onClick={() => router.select({ screen: item.screen } as Destination)}
            />
          ))}
        </Group>
      ))}
    </Screen>
  );
}
