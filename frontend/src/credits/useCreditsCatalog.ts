import { useCallback, useEffect, useState } from "react";
import { loadCreditsCatalog } from "./catalog";
import type { CreditsCatalog } from "./types";

export function useCreditsCatalog() {
  const [catalog, setCatalog] = useState<CreditsCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const reload = useCallback(() => setAttempt((value) => value + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(false);
    void loadCreditsCatalog(controller.signal).then((next) => {
      if (!controller.signal.aborted) setCatalog(next);
    }).catch(() => {
      if (!controller.signal.aborted) setError(true);
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [attempt]);
  return { catalog, loading, error, reload };
}
