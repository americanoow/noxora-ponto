import { useRef, useState } from "react";
import { errorMessage } from "./auth";
import {
  type BiometricStatus,
  type ExceptionGrant,
  type IdentificationMode,
  authorizeException,
  deleteTemplate,
  enrollFace,
  fileToBase64,
  getBiometricStatus,
  getIdentificationMode,
  grantConsent,
  revokeConsent,
  setIdentificationMode,
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
        setError("Envie até 5 imagens de no máximo 1 MB cada.");
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
      `Motivo da exceção para ${employeeName} (mínimo de 5 caracteres):`,
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
        Identificação
      </button>
      {open && (
        <div role="group" aria-label={`Identificação de ${employeeName}`}>
          {error && <p role="alert">{error}</p>}
          {canEdit && status && (
            <div>
              <p>
                Consentimento:{" "}
                {status.consent
                  ? `registrado (política ${status.consent.policy_version})`
                  : "não registrado"}
                {" — "}
                Cadastro facial:{" "}
                {status.template ? `ativo (${status.template.engine})` : "não cadastrado"}
              </p>
              {status.engine?.simulator && (
                <p role="note">
                  Motor SIMULADO (apenas desenvolvimento): não comprova identificação nem
                  antifraude.
                </p>
              )}
              {!status.engine && <p role="note">Motor biométrico não configurado.</p>}
              {!status.consent ? (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    act(() => grantConsent(companyId, employeeId, policy, evidence));
                  }}
                >
                  <input
                    aria-label="Versão da política"
                    value={policy}
                    onChange={(e) => setPolicy(e.target.value)}
                    required
                  />
                  <input
                    aria-label="Referência do termo assinado"
                    value={evidence}
                    onChange={(e) => setEvidence(e.target.value)}
                  />
                  <button type="submit">Registrar consentimento</button>
                </form>
              ) : (
                <>
                  <label>
                    Fotos para o cadastro (1 a 5; não são armazenadas)
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
                      Excluir cadastro facial
                    </button>
                  )}
                  <button onClick={() => act(() => revokeConsent(companyId, employeeId))}>
                    Revogar consentimento (exclui o cadastro)
                  </button>
                </>
              )}
            </div>
          )}
          <div>
            <button onClick={requestException}>Autorizar marcação por exceção</button>
            {grant && (
              <p role="status">
                Código de exceção de {employeeName}:{" "}
                <code aria-label="Código de exceção">{grant.code}</code>. Válido por poucos minutos
                e uso único; informe ao funcionário, que o digita no tablet. Não será exibido
                novamente. <button onClick={() => setGrant(null)}>Ocultar</button>
              </p>
            )}
          </div>
        </div>
      )}
    </span>
  );
}

/** Política de identificação da empresa: matrícula (não é identificação forte) ou verificação facial. */
export function IdentificationModePanel({
  companyId,
  canEdit,
}: {
  companyId: number;
  canEdit: boolean;
}) {
  const [mode, setMode] = useState<IdentificationMode | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getIdentificationMode(companyId)
      .then((value) => setMode(value.mode))
      .catch((e) => setError(errorMessage(e)));
  }, [companyId]);

  if (error) return <p role="alert">{error}</p>;
  if (!mode) return <p>Carregando…</p>;
  return (
    <section>
      <h4>Identificação do trabalhador no tablet</h4>
      <select
        aria-label="Modo de identificação"
        value={mode}
        disabled={!canEdit}
        onChange={(e) => {
          const next = e.target.value as IdentificationMode;
          setError(null);
          setIdentificationMode(companyId, next)
            .then((value) => setMode(value.mode))
            .catch((err) => setError(errorMessage(err)));
        }}
      >
        <option value="registration">Somente matrícula (não é identificação forte)</option>
        <option value="face">Verificação facial com vivacidade (ou exceção autorizada)</option>
      </select>
      {mode === "face" && (
        <p>
          No modo facial só vale verificação facial aprovada ou exceção autorizada. Sem um motor
          biométrico real configurado, os tablets não conseguirão registrar ponto.
        </p>
      )}
    </section>
  );
}
