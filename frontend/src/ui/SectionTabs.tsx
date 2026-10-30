import type { Destination, ScreenName } from "../lib/router";
import { useRouter } from "../lib/router";
import { Segmented } from "./kit";

/** Abas que compartilham o período e o funcionário escolhidos: trocar de aba não os perde. */
const PERIOD_SCREENS = new Set<ScreenName>(["timesheet", "records"]);

/** Abas de uma seção do menu: telas irmãs que antes eram itens separados da navegação. */
export function SectionTabs({
  tabs,
  current,
}: {
  tabs: [ScreenName, string][];
  current: ScreenName;
}) {
  const router = useRouter();
  return (
    <div className="section-tabs">
      <Segmented
        label="Partes desta seção"
        value={current}
        options={tabs}
        onChange={(screen) => {
          const carried: Record<string, unknown> = {};
          const here = router.top as Record<string, unknown>;
          if (PERIOD_SCREENS.has(current) && PERIOD_SCREENS.has(screen))
            for (const key of ["employeeId", "from", "to"])
              if (here[key] !== undefined) carried[key] = here[key];
          router.select({ screen, ...carried } as Destination);
        }}
      />
    </div>
  );
}
