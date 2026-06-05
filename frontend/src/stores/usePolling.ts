import { useCallback, useEffect, useRef, useState } from "react";

export function usePolling<T>(load: () => Promise<T>, intervalMs: number) {
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<string | undefined>();
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const next = await load();
      if (!mounted.current) return;
      setData(next);
      setError(undefined);
    } catch (err) {
      if (!mounted.current) return;
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [load]);

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

