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

export function SpellingControls({ mode, query, onModeChange, onAccept }: {
  mode: SpellingMode;
  query: string;
  onModeChange: (value: SpellingMode) => void;
  onAccept: (value: string) => void;
}) {
  const [result, setResult] = useState<{ query: string; changes: SpellingChange[]; failed?: boolean }>();
  useEffect(() => {
    setResult(undefined);
    if (mode !== "suggest" || query.trim().length < 5 || query.length > QUERY_MAX_LENGTH) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const { changes } = await api.spelling(query, controller.signal);
        if (!controller.signal.aborted) setResult({ query, changes });
      } catch {
        if (!controller.signal.aborted) setResult({ query, changes: [], failed: true });
      }
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [mode, query]);

  const current = mode === "suggest" && result?.query === query ? result : undefined;
  return (
    <div className="spelling-controls">
      <div className="spelling-modes" role="group" aria-label="Исправление опечаток">
        <span aria-hidden="true">Опечатки</span>
        {modes.map(([value, label]) => (
          <button type="button" key={value} aria-pressed={mode === value} onClick={() => onModeChange(value)}>
            {label}
          </button>
        ))}
      </div>
      {current?.failed && <p className="hint" role="status">Подсказки временно недоступны.</p>}
      {Boolean(current?.changes.length) && (
        <div className="spelling-suggestions" role="group" aria-label="Варианты исправления">
          <span>Заменить</span>
          {current?.changes.map(({ start, end, original, replacement }) => (
            <button type="button" key={start} aria-label={`Заменить ${original} на ${replacement}`} onClick={() => {
              // API offsets count Unicode code points, including emoji before the word.
              const characters = Array.from(query);
              onAccept(characters.slice(0, start).join("") + replacement + characters.slice(end).join(""));
            }}>
              {original} → <strong>{replacement}</strong>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
