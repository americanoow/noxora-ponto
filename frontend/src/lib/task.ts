import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage } from "../auth";

export interface TaskState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/**
 * Equivalente ao `.task {}` da SwiftUI: trabalho assíncrono fora da renderização, cancelado
 * automaticamente quando a tela sai ou quando as dependências mudam (resultado obsoleto é descartado).
 */
export function useTask<T>(
  work: (signal: AbortSignal) => Promise<T>,
  deps: unknown[],
): TaskState<T> {
  const [state, setState] = useState<{ data: T | null; error: string | null; loading: boolean }>({
    data: null,
    error: null,
    loading: true,
  });
  const [tick, setTick] = useState(0);
  const workRef = useRef(work);
  workRef.current = work;

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    workRef
      .current(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ data, error: null, loading: false });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setState({ data: null, error: errorMessage(error), loading: false });
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}

/** Ação do usuário (salvar, aprovar…): estado de envio e erro legível. */
export function useAction() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async <T>(fn: () => Promise<T>): Promise<T | undefined> => {
    setPending(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(errorMessage(e));
      return undefined;
    } finally {
      setPending(false);
    }
  }, []);
  return { pending, error, run, setError };
}
