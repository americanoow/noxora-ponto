import { useCallback, useSyncExternalStore } from "react";

/**
 * Equivalente ao `@Observable` da SwiftUI: estado de um modelo de tela com assinatura por propriedade.
 * Componentes leem com `useObservable(model, (s) => s.campo)` e só renderizam de novo quando o valor
 * selecionado muda (comparação por `Object.is`), não a cada alteração do modelo.
 */
export class Observable<S extends object> {
  private listeners = new Set<() => void>();

  constructor(protected _state: S) {}

  get state(): S {
    return this._state;
  }

  protected set(patch: Partial<S>) {
    this._state = { ...this._state, ...patch };
    this.listeners.forEach((listener) => listener());
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
}

export function useObservable<S extends object, T>(
  model: Observable<S>,
  select: (state: S) => T,
): T {
  const get = useCallback(() => select(model.state), [model, select]);
  return useSyncExternalStore(model.subscribe, get, get);
}
