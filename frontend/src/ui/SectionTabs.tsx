import type { Destination, ScreenName } from "../lib/router";
import { useRouter } from "../lib/router";
import { Segmented } from "./kit";

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
        onChange={(screen) => router.select({ screen } as Destination)}
      />
    </div>
  );
}
