import { useCallback, useEffect, useRef, useState } from "react";

type Options<T> = {
  keepData?: boolean;
  merge?: (previous: T | null, next: T) => T;
};

/** One request lane. Aborting AND checking controller identity protects even
 * against a response already queued when a new operation starts. */
export function useTask<T>() {
  const active = useRef<AbortController | null>(null);
  const [data, setData] = useState<T | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const reset = useCallback(() => {
    active.current?.abort();
    active.current = null;
    setData(null);
    setPending(false);
    setError(null);
  }, []);
  const run = useCallback(
    async (
      operation: (signal: AbortSignal) => Promise<T>,
      options: Options<T> = {},
    ) => {
      active.current?.abort();
      const controller = new AbortController();
      active.current = controller;
      setPending(true);
      setError(null);
      if (!options.keepData) setData(null);
      try {
        const next = await operation(controller.signal);
        if (active.current === controller && !controller.signal.aborted) {
          setData((previous) =>
            options.merge ? options.merge(previous, next) : next,
          );
        }
      } catch (failure) {
        if (active.current === controller && !controller.signal.aborted)
          setError(failure);
      } finally {
        if (active.current === controller && !controller.signal.aborted) {
          active.current = null;
          setPending(false);
        }
      }
    },
    [],
  );
  useEffect(
    () => () => {
      active.current?.abort();
      active.current = null;
    },
    [],
  );
  return {
    data,
    pending,
    error,
    run,
    reset,
    busy: () => active.current !== null,
  };
}
