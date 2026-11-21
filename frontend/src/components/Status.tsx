import { errorMessage } from "../api/client";

export function Loading({ children }: { children: string }) {
  return (
    <p className="status" role="status">
      <span className="loading-dot" aria-hidden="true" />
      {children}
    </p>
  );
}
export function Failure({
  error,
  retry,
}: {
  error: unknown;
  retry: () => void;
}) {
  return (
    <div className="failure" role="alert">
      <p>{errorMessage(error)}</p>
      <button type="button" onClick={retry}>
        Повторить
      </button>
    </div>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children: string;
}) {
  return (
    <div className="empty">
      <span aria-hidden="true" className="empty-icon">
        ≡
      </span>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function MessageDate({ value }: { value: string | null }) {
  return value ? (
    <time dateTime={value}>{value.split("-").reverse().join(".")}</time>
  ) : (
    <span>Дата неизвестна</span>
  );
}
