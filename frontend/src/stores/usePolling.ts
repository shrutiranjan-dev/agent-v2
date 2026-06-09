import { useCallback, useEffect, useRef, useState } from "react";

export function usePolling<T>(load: () => Promise<T>, intervalMs: number) {
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<string | undefined>();
  const mounted = useRef(true);
  const loadRef = useRef(load);
  const loadingRef = useRef(false);

  loadRef.current = load;

  const refresh = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    try {
      const next = await loadRef.current();
      if (!mounted.current) return;
      setData(next);
      setError(undefined);
    } catch (err) {
      if (!mounted.current) return;
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      loadingRef.current = false;
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const id = window.setInterval(refresh, intervalMs);
    return () => {
      mounted.current = false;
      window.clearInterval(id);
    };
  }, [intervalMs, refresh]);

  return { data, error, refresh };
}

