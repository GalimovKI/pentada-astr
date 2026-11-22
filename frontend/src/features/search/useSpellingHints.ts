import { useEffect, useState } from "react";
import { api, QUERY_MAX_LENGTH, type SpellingChange } from "../../api/client";

type Hints = {
  query: string;
  cursor: number;
  changes: SpellingChange[];
  completions: SpellingChange[];
  failed?: boolean;
};

export function useSpellingHints(query: string, cursor: number, enabled: boolean) {
  const [result, setResult] = useState<Hints>();
  useEffect(() => {
    setResult(undefined);
    if (!enabled || query.trim().length < 3 || query.length > QUERY_MAX_LENGTH) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const response = await api.spelling(query, cursor, controller.signal);
        if (!controller.signal.aborted) setResult({
          query, cursor, changes: response.changes,
          completions: response.completions ?? [],
        });
      } catch {
        if (!controller.signal.aborted) setResult({ query, cursor, changes: [], completions: [], failed: true });
      }
    }, 180);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query, cursor, enabled]);
  return enabled && result?.query === query && result.cursor === cursor ? result : undefined;
}
