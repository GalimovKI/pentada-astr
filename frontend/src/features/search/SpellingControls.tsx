import { useEffect, useState } from "react";
import { api, QUERY_MAX_LENGTH, type SpellingChange } from "../../api/client";

const modes = [
  ["off", "Выкл."],
  ["suggest", "Подсказывать при вводе"],
  ["silent", "Исправлять при поиске"],
] as const;
export type SpellingMode = typeof modes[number][0];

export function readSpellingMode(): SpellingMode {
  try {
    const saved = localStorage.getItem("smartmail.spelling");
    if (saved === "suggest" || saved === "silent") return saved;
  } catch { /* Private browsing can disable storage. */ }
  return "off";
}

export function SpellingModes({ mode, onChange }: {
  mode: SpellingMode;
  onChange: (value: SpellingMode) => void;
}) {
  return (
    <div className="spelling-controls spelling-modes" role="group" aria-label="Исправление опечаток">
      <span aria-hidden="true">Опечатки</span>
      {modes.map(([value, label]) => (
        <button type="button" key={value} aria-pressed={mode === value} onClick={() => onChange(value)}>
          {label}
        </button>
      ))}
    </div>
  );
}

type Hints = {
  query: string;
  cursor: number;
  changes: SpellingChange[];
  completions: SpellingChange[];
  failed?: boolean;
};

export function SpellingSuggestions({ query, cursor, onAccept }: {
  query: string;
  cursor: number;
  onAccept: (change: SpellingChange) => void;
}) {
  const [result, setResult] = useState<Hints>();
  useEffect(() => {
    setResult(undefined);
    if (query.trim().length < 3 || query.length > QUERY_MAX_LENGTH) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const response = await api.spelling(query, cursor, controller.signal);
        if (!controller.signal.aborted) setResult({ query, cursor, changes: response.changes, completions: response.completions ?? [] });
      } catch {
        if (!controller.signal.aborted) setResult({ query, cursor, changes: [], completions: [], failed: true });
      }
    }, 180);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query, cursor]);
  if (!result || result.query !== query || result.cursor !== cursor) return null;
  if (result.failed) return <p className="hint" role="status">Подсказки временно недоступны.</p>;
  const beforeCursor = Array.from(query).slice(0, cursor).join("");
  if (!result.completions.length && !result.changes.length) {
    return /[а-яёa-z]{3}$/iu.test(beforeCursor)
      ? <p className="hint" role="status">Подсказок нет.</p> : null;
  }
  return (
    <div className="spelling-controls" aria-live="polite">
      {result.completions.length > 0 && (
        <div className="spelling-suggestions" role="group" aria-label="Продолжения слова">
          <span>Дописать</span>
          {result.completions.map(change => (
            <button type="button" key={change.replacement} onClick={() => onAccept(change)}>
              {change.replacement}
            </button>
          ))}
        </div>
      )}
      {result.changes.length > 0 && (
        <div className="spelling-suggestions" role="group" aria-label="Варианты исправления">
          <span>Заменить</span>
          {result.changes.map(change => (
            <button type="button" key={change.start}
              aria-label={`Заменить ${change.original} на ${change.replacement}`} onClick={() => onAccept(change)}>
              {change.original} → <strong>{change.replacement}</strong>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
