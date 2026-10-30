import { useCallback, useEffect, useState } from "react";
import { errorMessage } from "./auth";
import {
  type Connectivity,
  type Device,
  type DeviceStatus,
  type DeviceWithCode,
  createDevice,
  listDevices,
  reissueDeviceCode,
  revokeDevice,
  updateDeviceLocation,
} from "./devicesApi";
import { type Unit, listUnits } from "./operationsApi";

const STATUS: Record<DeviceStatus, string> = {
  pending: "Falta ativar no tablet",
  active: "Ativo",
  revoked: "Bloqueado",
};
const CONNECTIVITY: Record<Connectivity, string> = {
  online: "Conectado",
  stale: "Sem sinal há algum tempo",
  offline: "Sem internet",
  never: "Nunca se conectou",
};

export function DevicesTab({ companyId, canEdit }: { companyId: number; canEdit: boolean }) {
  return <DevicesPanel key={`${companyId}:${canEdit}`} companyId={companyId} canEdit={canEdit} />;
}

function DevicesPanel({ companyId, canEdit }: { companyId: number; canEdit: boolean }) {
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [units, setUnits] = useState<Unit[]>([]);
  const [error, setError] = useState<string | null>(null);
  // O código de ativação é exibido uma única vez, só neste estado local (nunca é persistido).
  const [issued, setIssued] = useState<DeviceWithCode | null>(null);
  const [name, setName] = useState("");
  const [unit, setUnit] = useState("");

  const load = useCallback(() => {
    listDevices(companyId)
      .then((value) => {
        setDevices(value);
        setError(null);
      })
      .catch((e) => setError(errorMessage(e)));
  }, [companyId]);

  useEffect(() => {
    load();
    if (canEdit)
      listUnits(companyId)
        .then(setUnits)
        .catch(() => undefined);
  }, [load, canEdit, companyId]);

  const act = (fn: () => Promise<unknown>, after?: (result: unknown) => void) => {
    setError(null);
    fn()
      .then((result) => {
        after?.(result);
        load();
      })
      .catch((e) => setError(errorMessage(e)));
  };

  return (
    <div>
      {error && <p role="alert">{error}</p>}
      {issued && (
        <div role="status">
          <p>
            Código para ativar o tablet <strong>{issued.name}</strong>:{" "}
            <code aria-label="Código de ativação">{issued.activation_code}</code>
          </p>
          <p>
            Digite este código no tablet em até 15 minutos. Ele não será mostrado de novo, então
            anote agora. <button onClick={() => setIssued(null)}>Ocultar</button>
          </p>
        </div>
      )}
      <ul>
        {devices?.map((d) => (
          <li key={d.id}>
            <strong>{d.name}</strong> — {d.unit_name} — {STATUS[d.status]}
            {d.status === "active" && ` — ${CONNECTIVITY[d.connectivity]}`}
            {d.app_version && ` — versão do aplicativo ${d.app_version}`}
            {d.last_seen_at &&
              ` — última conexão em ${new Date(d.last_seen_at).toLocaleString("pt-BR")}`}
            {d.collect_location && " — registra o local das batidas"}
            {canEdit && (
              <>
                {d.status !== "revoked" && (
                  <button onClick={() => act(() => revokeDevice(companyId, d.id))}>
                    Bloquear tablet
                  </button>
                )}
                <button
                  onClick={() =>
                    act(
                      () => reissueDeviceCode(companyId, d.id),
                      (r) => setIssued(r as DeviceWithCode),
                    )
                  }
                >
                  {d.status === "pending" ? "Gerar novo código" : "Gerar novo código de ativação"}
                </button>
                <button
                  onClick={() => {
                    if (d.collect_location) {
                      act(() => updateDeviceLocation(companyId, d.id, false, ""));
                    } else {
                      const reason = window.prompt(
                        "Por que é preciso registrar o local das batidas? (explique em poucas palavras)",
                      );
                      if (reason?.trim())
                        act(() => updateDeviceLocation(companyId, d.id, true, reason.trim()));
                    }
                  }}
                >
                  {d.collect_location
                    ? "Parar de registrar o local"
                    : "Registrar o local das batidas"}
                </button>
              </>
            )}
          </li>
        ))}
      </ul>
      {devices?.length === 0 && <p>Nenhum tablet cadastrado ainda.</p>}
      {canEdit && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            act(
              () => createDevice(companyId, name, Number(unit)),
              (r) => {
                setIssued(r as DeviceWithCode);
                setName("");
              },
            );
          }}
        >
          <h4>Novo tablet</h4>
          <input
            aria-label="Nome do tablet"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <select
            aria-label="Unidade do tablet"
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            required
          >
            <option value="">Unidade…</option>
            {units
              .filter((u) => u.is_active)
              .map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
          </select>
          <button type="submit">Cadastrar e gerar código de ativação</button>
        </form>
      )}
    </div>
  );
}
