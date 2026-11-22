import { QueryInput } from "./QueryInput";

export function SearchForm({ value, error, ready, example, onChange, onSubmit }: {
  value: string;
  error: string | null;
  ready: boolean;
  example?: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
}) {
  return (
    <form className="search-form" role="search" noValidate
      onSubmit={event => { event.preventDefault(); onSubmit(); }}>
      <label htmlFor="query" className="sr-only">Найти письмо своими словами</label>
      <div className="search-row">
        <QueryInput value={value} example={example} invalid={Boolean(error)} onChange={onChange} />
        <button className="primary" type="submit" disabled={!ready}>Найти</button>
      </div>
      {error ? <p id="query-error" className="validation" role="alert">{error}</p> :
        <p id="query-help" className="sr-only">Введите слова или опишите письмо.</p>}
    </form>
  );
}
