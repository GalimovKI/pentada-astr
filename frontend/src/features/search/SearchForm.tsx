import { type ReactNode, useRef, useState } from "react";
import { SpellingControls, type SpellingMode } from "./SpellingControls";
import { queryError } from "../../app/validation";

export function SearchForm({
  onSearch,
  pending,
  threshold,
  model,
  modelPicker,
  spellingMode,
  onSpellingMode,
}: {
  onSearch: (query: string, similarity?: number) => void;
  threshold?: number;
  model?: string;
  modelPicker: ReactNode;
  pending: boolean;
  spellingMode?: SpellingMode;
  onSpellingMode: (mode: SpellingMode) => void;
}) {
  const queryInput = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <form
      className="search-form"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        const issue = queryError(draft);
        setError(issue);
        if (issue) return;
        const field = event.currentTarget.elements.namedItem("similarity") as HTMLInputElement | null;
        if (field && !field.reportValidity()) return;
        onSearch(draft, field?.valueAsNumber);
      }}
    >
      <div className="query-field">
        <label htmlFor="query">Найти письмо своими словами</label>
        <div className="search-row">
          <input
            ref={queryInput}
            id="query"
            autoCorrect={spellingMode ? "off" : undefined}
            spellCheck={spellingMode ? false : undefined}
            type="search"
            placeholder="Например, перенос встречи"
            value={draft}
            aria-invalid={!!error}
            aria-describedby={error ? "query-error" : "query-help"}
            onChange={(event) => {
              setDraft(event.target.value);
              setError(null);
            }}
          />
          <button className="primary" type="submit">
            Найти
          </button>
        </div>
      </div>
      {modelPicker}
      {threshold !== undefined && (
        <div className="field similarity-field">
          <label htmlFor="similarity">Порог отбора писем</label>
          <input key={model} id="similarity" name="similarity" type="number" required min={model === "e5-cosine" ? -1 : 0} max="1" step="any"
            defaultValue={threshold} aria-describedby="similarity-help" />
          <p className="sr-only" id="similarity-help">{model === "e5-cosine" ? "Косинусное сходство от −1 до 1." : "Оценка релевантности от 0 до 1."} Все письма с оценкой от порога включительно попадут в выдачу.</p>
        </div>
      )}
      {spellingMode && (
        <SpellingControls
          mode={spellingMode} onModeChange={onSpellingMode}
          query={draft} onAccept={(next) => {
            setDraft(next);
            setError(null);
            queryInput.current?.focus();
          }}
        />
      )}
      {error ? (
        <p id="query-error" className="validation" role="alert">
          {error}
        </p>
      ) : (
        <p id="query-help" className="sr-only">
          {pending
            ? "Ищем письма. Можно отправить новый запрос."
            : "Опишите, что помните. Поиск учитывает выбранную дату сценария."}
        </p>
      )}
    </form>
  );
}
