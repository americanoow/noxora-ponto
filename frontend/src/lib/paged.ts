import { useCallback, useEffect, useState } from "react";
import { errorMessage } from "../auth";
import type { Page } from "../operationsApi";
import { useTask } from "./task";

export interface PagedList<T> {
  items: T[];
  /** Total real no servidor (pode ser maior que `items.length`). */
  count: number;
  /** Já houve uma resposta da primeira página. */
  ready: boolean;
  loading: boolean;
  error: string | null;
  hasMore: boolean;
  loadMore: () => void;
  reload: () => void;
}

/**
 * Lista paginada com "Mostrar mais": a primeira página vem de `useTask` (cancelada ao trocar as
 * dependências) e as seguintes são acrescentadas sem esconder o total real.
 */
export function usePaged<T>(
  fetchPage: (page: number) => Promise<Page<T>>,
  deps: unknown[],
): PagedList<T> {
  const first = useTask(() => fetchPage(1), deps);
  const [more, setMore] = useState<{ items: T[]; page: number; next: boolean | null }>({
    items: [],
    page: 1,
    next: null,
  });
  const [busy, setBusy] = useState(false);
  const [moreError, setMoreError] = useState<string | null>(null);

  useEffect(() => {
    setMore({ items: [], page: 1, next: null });
    setMoreError(null);
  }, [first.data]);

  const loadMore = useCallback(() => {
    if (busy) return;
    setBusy(true);
    setMoreError(null);
    fetchPage(more.page + 1)
      .then((next) =>
        setMore((m) => ({
          items: [...m.items, ...next.results],
          page: m.page + 1,
          next: Boolean(next.next),
        })),
      )
      .catch((error: unknown) => setMoreError(errorMessage(error)))
      .finally(() => setBusy(false));
  }, [busy, fetchPage, more.page]);

  return {
    items: [...(first.data?.results ?? []), ...more.items],
    count: first.data?.count ?? 0,
    ready: first.data !== null,
    loading: first.loading || busy,
    error: first.error ?? moreError,
    hasMore: more.next ?? Boolean(first.data?.next),
    loadMore,
    reload: first.reload,
  };
}
