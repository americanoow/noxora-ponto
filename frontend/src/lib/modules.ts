import { createContext, useContext } from "react";

/** Módulos opcionais da empresa. Desligados, somem da navegação e das telas. */
export interface Modules {
  /** Situação da equipe (disponível, em pausa, externo…): informada à mão, nunca altera o ponto. */
  availability: boolean;
  reload: () => void;
}

export const ModulesCtx = createContext<Modules>({ availability: false, reload: () => undefined });
export const useModules = () => useContext(ModulesCtx);
