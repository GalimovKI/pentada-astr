import { useState } from "react";
import { queryError } from "../../app/validation";

export function SearchForm({
  onSearch,
  pending,
  threshold,
  model,
}: {
  onSearch: (query: string, similarity?: number) => void;
  threshold?: number;
  model?: string;
  pending: boolean;
}) {
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
      {threshold !== undefined && (
        <div className="field similarity-field">
          <label htmlFor="similarity">Порог отбора писем</label>
          <input key={model} id="similarity" name="similarity" type="number" required min={model === "e5-cosine" ? -1 : 0} max="1" step="any"
            defaultValue={threshold} aria-describedby="similarity-help" />
          <p className="hint" id="similarity-help">{model === "e5-cosine" ? "Косинусное сходство от −1 до 1." : "Оценка релевантности от 0 до 1."} Все письма с оценкой от порога включительно попадут в выдачу.</p>
        </div>
      )}
      <label htmlFor="query">Найти письмо своими словами</label>
      <div className="search-row">
        <input
          id="query"
          type="search"
          placeholder="Например, письма о переносе встречи за вчера"
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
      {error ? (
        <p id="query-error" className="validation" role="alert">
          {error}
        </p>
      ) : (
        <p id="query-help" className="hint">
          {pending
            ? "Ищем письма. Можно отправить новый запрос."
            : "Опишите, что помните. Поиск учитывает выбранную дату сценария."}
        </p>
      )}
    </form>
  );
}
