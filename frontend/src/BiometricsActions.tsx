import { useRef, useState } from "react";
import { errorMessage } from "./auth";
import {
  type BiometricStatus,
  type ExceptionGrant,
  type IdentificationMode,
  type IdentificationPolicy,
  type OfflinePolicy,
  authorizeException,
  deleteTemplate,
  enrollFace,
  fileToBase64,
  getBiometricStatus,
  getIdentificationMode,
  grantConsent,
  revokeConsent,
  setIdentificationPolicy,
} from "./biometricsApi";
import { useEffect } from "react";

interface Props {
  companyId: number;
  employeeId: number;
  employeeName: string;
  canEdit: boolean;
}

/** Biometria (somente administrador) e exceção autorizada (administrador ou gestor do escopo). */
export function BiometricsActions({ companyId, employeeId, employeeName, canEdit }: Props) {
  const generation = useRef(0);
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<BiometricStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [policy, setPolicy] = useState("v1");
  const [evidence, setEvidence] = useState("");
  const [grant, setGrant] = useState<ExceptionGrant | null>(null);

  const act = (fn: () => Promise<BiometricStatus>) => {
    setError(null);
    fn()
      .then(setStatus)
      .catch((e) => setError(errorMessage(e)));
  };

  const toggle = () => {
    const next = !open;
    generation.current += 1;
    setGrant(null);
    setOpen(next);
    if (next && canEdit) act(() => getBiometricStatus(companyId, employeeId));
  };

  const onFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setError(null);
    try {
      if (files.length > 5 || Array.from(files).some((f) => f.size > 1_000_000)) {
        setError("Envie de 1 a 5 fotos, cada uma com no máximo 1 MB.");
        return;
      }
      const images = await Promise.all(Array.from(files).map(fileToBase64));
      act(() => enrollFace(companyId, employeeId, images));
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const requestException = () => {
    const reason = window.prompt(
      `Por que ${employeeName} precisa bater o ponto sem reconhecimento facial? (explique em pelo menos 5 letras)`,
    );
    if (!reason?.trim()) return;
    setError(null);
    setGrant(null);
    const current = ++generation.current;
    authorizeException(companyId, employeeId, reason.trim())
      .then((value) => {
        if (current === generation.current) setGrant(value);
      })
      .catch((e) => setError(errorMessage(e)));
  };

  return (
    <span>
      <button onClick={toggle} aria-expanded={open}>
        Identificação no tablet
      </button>
      {open && (
        <div role="group" aria-label={`Identificação de ${employeeName}`}>
          {error && <p role="alert">{error}</p>}
          {canEdit && status && (
            <div>
              <p>
                Autorização para usar o rosto:{" "}
                {status.consent ? "registrada" : "ainda não registrada"}
                {" — "}
                Rosto cadastrado: {status.template ? "sim" : "não"}
              </p>
              {status.engine?.simulator && (
                <p role="note">
                  Reconhecimento facial de TESTE: não use com funcionários reais, pois não garante
                  quem é a pessoa.
                </p>
              )}
              {!status.engine && (
                <p role="note">O reconhecimento facial ainda não foi configurado no sistema.</p>
              )}
              {!status.consent ? (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    act(() => grantConsent(companyId, employeeId, policy, evidence));
                  }}
                >
                  <input
                    aria-label="Versão do termo de autorização"
                    value={policy}
                    onChange={(e) => setPolicy(e.target.value)}
                    required
                  />
                  <input
                    aria-label="Número ou nome do termo assinado (opcional)"
                    value={evidence}
                    onChange={(e) => setEvidence(e.target.value)}
                  />
                  <button type="submit">Registrar autorização</button>
                </form>
              ) : (
                <>
                  <label>
                    Fotos do rosto para o cadastro (de 1 a 5; as fotos não ficam guardadas)
                    <input
                      type="file"
                      accept="image/jpeg,image/png"
                      multiple
                      onChange={(e) => {
                        void onFiles(e.target.files);
                        e.target.value = "";
                      }}
                    />
                  </label>
                  {status.template && (
                    <button onClick={() => act(() => deleteTemplate(companyId, employeeId))}>
                      Apagar o rosto cadastrado
                    </button>
                  )}
                  <button onClick={() => act(() => revokeConsent(companyId, employeeId))}>
                    Retirar a autorização (apaga o rosto cadastrado)
                  </button>
                </>
              )}
            </div>
          )}
          <div>
            <button onClick={requestException}>
              Liberar bater o ponto sem reconhecimento facial
            </button>
            {grant && (
              <p role="status">
                Código liberado para {employeeName}:{" "}
                <code aria-label="Código liberado">{grant.code}</code>. Vale por poucos minutos e só
                pode ser usado uma vez. Passe o código ao funcionário para ele digitar no tablet.
                Ele não será mostrado de novo.{" "}
                <button onClick={() => setGrant(null)}>Ocultar</button>
              </p>
            )}
          </div>
        </div>
      )}
    </span>
  );
}

/** Política de identificação e de marcação offline da empresa. */
export function IdentificationModePanel({
  companyId,
  canEdit,
}: {
  companyId: number;
  canEdit: boolean;
}) {
  const [policy, setPolicy] = useState<IdentificationPolicy | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getIdentificationMode(companyId)
      .then((value) => setPolicy({ ...value, offline_policy: value.offline_policy ?? "disabled" }))
      .catch((e) => setError(errorMessage(e)));
  }, [companyId]);

  if (error) return <p role="alert">{error}</p>;
  if (!policy) return <p>Carregando…</p>;

  const change = (changes: Partial<IdentificationPolicy>) => {
    setError(null);
    setIdentificationPolicy(companyId, changes)
      .then((value) => setPolicy({ ...value, offline_policy: value.offline_policy ?? "disabled" }))
      .catch((err) => setError(errorMessage(err)));
  };

  return (
    <section>
      <h4>Como o funcionário se identifica no tablet</h4>
      <select
        aria-label="Como o funcionário se identifica"
        value={policy.mode}
        disabled={!canEdit}
        onChange={(e) => change({ mode: e.target.value as IdentificationMode })}
      >
        <option value="registration">Só digitando a matrícula (menos seguro)</option>
        <option value="face">Reconhecimento facial (ou código liberado pelo gestor)</option>
      </select>
      {policy.mode === "face" && (
        <p>
          Com reconhecimento facial, só vale o rosto reconhecido ou um código liberado pelo gestor.
          Se o reconhecimento facial não estiver configurado no sistema, os tablets não conseguirão
          registrar o ponto.
        </p>
      )}
      <h4>Bater o ponto com o tablet sem internet</h4>
      <select
        aria-label="Bater o ponto sem internet"
        value={policy.offline_policy}
        disabled={!canEdit}
        onChange={(e) => change({ offline_policy: e.target.value as OfflinePolicy })}
      >
        <option value="disabled">Não permitir (sem internet, o tablet não registra)</option>
        <option value="registration_only">Permitir pela matrícula e revisar depois</option>
      </select>
      <p>
        O reconhecimento facial não funciona sem internet. Se você permitir, a batida sem internet
        usa só a matrícula (menos seguro), fica marcada para revisão e só recebe o número de
        registro e o comprovante quando o tablet voltar a ter internet.
      </p>
    </section>
  );
}
