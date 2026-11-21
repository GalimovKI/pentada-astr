import { useEffect, useRef } from "react";
import { api, type Context, type MessageResponse } from "../../api/client";
import { useTask } from "../../app/useTask";
import { Failure, Loading, MessageDate } from "../../components/Status";

export function MessageReader({
  context,
  id,
  onClose,
}: {
  context: Context;
  id: string;
  onClose: () => void;
}) {
  const { data, pending, error, run } = useTask<MessageResponse>();
  const heading = useRef<HTMLHeadingElement>(null);
  const load = () => void run((signal) => api.message(context, id, signal));
  useEffect(() => {
    void run((signal) => api.message(context, id, signal));
    heading.current?.focus();
  }, [context.mailbox, context.date, id, run]);
  return (
    <article className="reader" aria-label="Открытое письмо">
      <header className="reader-header">
        <button className="back" type="button" onClick={onClose}>
          ← К списку
        </button>
        <span className="eyebrow">Исходный текст</span>
        <h2 ref={heading} tabIndex={-1}>
          Письмо
        </h2>
        <p className="doc-id">{id}</p>
        {data && (
          <div className="reader-meta">
            <MessageDate value={data.item.doc_dt} />
            <span>{data.item.synthetic_user}</span>
          </div>
        )}
      </header>
      {pending && <Loading>Загружаем письмо…</Loading>}
      {error != null && <Failure error={error} retry={load} />}
      {data && <div className="message-body">{data.item.doc}</div>}
    </article>
  );
}
