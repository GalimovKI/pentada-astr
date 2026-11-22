import { useLayoutEffect, useRef, useState } from "react";
import { type SpellingChange } from "../../api/client";
import { useSpellingHints } from "./useSpellingHints";

export function QueryInput({ value, invalid, example = "перенос встречи", onChange }: {
  value: string;
  invalid: boolean;
  example?: string;
  onChange: (value: string) => void;
}) {
  const field = useRef<HTMLInputElement>(null);
  const acceptedCaret = useRef<number | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const measure = useRef<HTMLSpanElement>(null);
  const [cursor, setCursor] = useState(0);
  const [focused, setFocused] = useState(false);
  const [composing, setComposing] = useState(false);
  const [selection, setSelection] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [alternatives, setAlternatives] = useState(false);
  const [fits, setFits] = useState(false);
  const enabled = focused && !selection && !composing && !dismissed;
  const result = useSpellingHints(value, cursor, enabled);
  const changes = result?.changes ?? [];
  const activeChange = changes.find(change => change.end === cursor);
  const choices = [
    ...(activeChange ? [activeChange] : []),
    ...(result?.completions ?? []),
    ...changes.filter(change => change !== activeChange),
  ];
  const primary = choices[0];
  const completion = result?.completions.includes(primary);
  const atEnd = primary?.end === Array.from(value).length && primary?.end === cursor;
  const suffix = completion && primary ? primary.replacement.slice(primary.original.length) : "";
  const dock = !atEnd || !fits;

  useLayoutEffect(() => {
    const ruler = measure.current, container = box.current;
    if (!ruler || !container) return;
    const update = () => setFits(ruler.offsetWidth + 42 < container.clientWidth);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(ruler);
    observer.observe(container);
    return () => observer.disconnect();
  }, [primary?.replacement, value]);

  function caret(input: HTMLInputElement) {
    const next = Array.from(input.value.slice(0, input.selectionEnd ?? input.value.length)).length;
    setSelection(input.selectionStart !== input.selectionEnd);
    if (next !== cursor) {
      setCursor(next);
      setDismissed(false);
      setAlternatives(false);
    }
  }

  useLayoutEffect(() => {
    const offset = acceptedCaret.current;
    if (offset === null || !field.current) return;
    acceptedCaret.current = null;
    field.current.focus();
    field.current.setSelectionRange(offset, offset);
  }, [value]);

  function accept(change: SpellingChange) {
    const letters = Array.from(value);
    const prefix = letters.slice(0, change.start).join("") + change.replacement;
    const next = prefix + letters.slice(change.end).join("");
    acceptedCaret.current = prefix.length;
    onChange(next);
    setCursor(Array.from(prefix).length);
    setDismissed(true);
    setAlternatives(false);
  }

  function label(item: SpellingChange) {
    return result?.completions.includes(item) ? item.replacement : `Заменить ${item.original} на ${item.replacement}`;
  }
  return (
    <div ref={box} className={`query-input${primary && dock ? " hint-docked" : ""}`}
      onFocus={() => setFocused(true)}
      onBlur={event => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          setFocused(false);
          setAlternatives(false);
        }
      }}>
      <input ref={field} id="query" type="search" value={value}
        autoCorrect="off" spellCheck={false}
        autoComplete="off"
        aria-autocomplete="inline"
        placeholder={`Например, ${example}`} aria-invalid={invalid}
        aria-describedby={invalid ? "query-error" : primary ? "inline-hint-help" : "query-help"}
        onSelect={event => caret(event.currentTarget)}
        onCompositionStart={() => setComposing(true)} onCompositionEnd={() => setComposing(false)}
        onChange={event => {
          caret(event.currentTarget);
          setDismissed(false);
          setAlternatives(false);
          onChange(event.target.value);
        }}
        onKeyDown={event => {
          if (!primary || event.nativeEvent.isComposing || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
          if (event.key === "Tab") {
            event.preventDefault();
            accept(primary);
          } else if (event.key === "Escape") {
            event.preventDefault();
            setDismissed(true);
            setAlternatives(false);
          } else if (event.key === "ArrowDown" && choices.length > 1) {
            event.preventDefault();
            setAlternatives(true);
            requestAnimationFrame(() => box.current?.querySelector<HTMLButtonElement>(".hint-options button")?.focus());
          }
        }} />
      {primary && <>
        <span className="hint-ruler" aria-hidden="true"><span ref={measure}>{value}{suffix || " → " + primary.replacement}{choices.length > 1 ? "　⌄" : ""}</span></span>
        <div className={`inline-hint${dock ? " docked" : ""}`}>
          {!dock && <span aria-hidden="true" className="hint-prefix">{value}</span>}
          <button type="button" className={`hint-word ${completion && !dock ? "ghost" : "corrected"}`}
            tabIndex={-1} aria-label={label(primary)}
            onMouseDown={event => event.preventDefault()} onClick={() => accept(primary)}>
            {completion && !dock ? suffix : (!completion && primary.end !== cursor
              ? `${primary.original} → ${primary.replacement}` : primary.replacement)}
          </button>
          {choices.length > 1 && <button type="button" className="more-hints" aria-label="Другие варианты"
            aria-expanded={alternatives} onMouseDown={event => event.preventDefault()}
            onClick={() => setAlternatives(!alternatives)}>⌄</button>}
        </div>
        <span className="sr-only" role="status" id="inline-hint-help">Подсказка: {label(primary)}. Tab — принять, Escape — скрыть.</span>
        {alternatives && <div className="hint-options" role="group" aria-label="Другие варианты"
          onKeyDown={event => {
            if (event.key === "Escape") { setAlternatives(false); field.current?.focus(); }
          }}>
          {choices.slice(1).map(change => <button type="button" key={change.start + ":" + change.replacement}
            aria-label={label(change)} onMouseDown={event => event.preventDefault()}
            onClick={() => accept(change)}>{change.replacement}</button>)}
        </div>}
      </>}
      {result?.failed && <span className="sr-only" role="status">Подсказки временно недоступны.</span>}
    </div>
  );
}
