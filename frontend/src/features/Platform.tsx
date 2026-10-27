import { useState } from "react";
import {
  listPlatformPlans,
  listPlatformSubscriptions,
  runBilling,
  startSubscription,
} from "../api/operational";
import { dateBR } from "../lib/format";
import { useAction, useTask } from "../lib/task";
import { PlatformPanel } from "../screens";
import { Badge, ErrorText, Group, Loading, Screen } from "../ui/kit";

export function PlatformScreen() {
  const rows = useTask(() => listPlatformSubscriptions(), []);
  const plans = useTask(() => listPlatformPlans(), []);
  const [plan, setPlan] = useState("essencial");
  const [result, setResult] = useState<string | null>(null);
  const { pending, error, run } = useAction();
  return (
    <Screen
      title="Plataforma"
      subtitle="Equipe Noxora: empresas e assinaturas. Sem acesso aos dados internos das empresas."
      toolbar={
        <button
          disabled={pending}
          onClick={() =>
            void run(async () => {
              const r = await runBilling();
              setResult(
                `${r.invoices_issued} fatura(s) emitida(s), ${r.subscriptions_suspended} assinatura(s) suspensa(s).`,
              );
              rows.reload();
            })
          }
        >
          Rodar cobrança agora
        </button>
      }
    >
      {result && (
        <p role="status" className="notice">
          {result}
        </p>
      )}
      <ErrorText message={error ?? rows.error} />
      <Group title="Assinaturas">
        {rows.loading && !rows.data ? (
          <Loading />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Empresa</th>
                <th>Plano</th>
                <th>Situação</th>
                <th>Uso</th>
                <th>Faturas abertas</th>
              </tr>
            </thead>
            <tbody>
              {rows.data?.map((r) => (
                <tr key={r.company.id}>
                  <td>
                    {r.company.name}
                    {!r.company.is_active && <Badge tone="seal">Inativa</Badge>}
                  </td>
                  <td>{r.subscription?.plan.name ?? "—"}</td>
                  <td>
                    {r.subscription ? (
                      <Badge
                        tone={
                          r.subscription.status === "active" || r.subscription.status === "trialing"
                            ? "tint"
                            : "seal"
                        }
                      >
                        {r.subscription.status_label}
                      </Badge>
                    ) : (
                      <span className="toolbar">
                        <select
                          aria-label={`Plano para ${r.company.name}`}
                          value={plan}
                          onChange={(e) => setPlan(e.target.value)}
                        >
                          {plans.data?.map((p) => (
                            <option key={p.code} value={p.code}>
                              {p.name}
                            </option>
                          ))}
                        </select>
                        <button
                          disabled={pending}
                          onClick={() =>
                            void run(async () => {
                              await startSubscription(r.company.id, plan, 14);
                              rows.reload();
                            })
                          }
                        >
                          Iniciar teste
                        </button>
                      </span>
                    )}
                    {r.subscription?.trial_ends_at && (
                      <div style={{ fontSize: 12, color: "var(--ink-3)" }}>
                        teste até {dateBR(r.subscription.trial_ends_at)}
                      </div>
                    )}
                  </td>
                  <td className="num">
                    {r.usage.active_employees} funcionários, {r.usage.active_devices} tablets
                  </td>
                  <td className="num">{r.open_invoices}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Group>
      <Group title="Empresas" padded>
        <div className="legacy">
          <PlatformPanel />
        </div>
      </Group>
    </Screen>
  );
}
