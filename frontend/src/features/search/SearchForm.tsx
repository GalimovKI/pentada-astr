import { useState } from "react";
import { queryError } from "../../app/validation";

export function SearchForm({
  onSearch,
  pending,
}: {
  onSearch: (query: string) => void;
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
        if (!issue) onSearch(draft);
      }}
    >
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
