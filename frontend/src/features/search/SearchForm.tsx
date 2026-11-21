import { useState } from "react";
import { queryError } from "../../app/validation";

export function SearchForm({
  onSearch,
  pending,
  threshold,
}: {
  onSearch: (query: string, similarity?: number) => void;
  threshold?: number;
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
          <label htmlFor="similarity">Минимальное косинусное сходство</label>
          <input id="similarity" name="similarity" type="number" required min="-1" max="1" step="any"
            defaultValue={threshold} aria-describedby="similarity-help" />
          <p className="hint" id="similarity-help">От −1 до 1. Чем выше порог, тем меньше писем пройдёт отбор.</p>
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
