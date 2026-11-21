import { parseLetter } from "./parseLetter";
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
  const letter = data && parseLetter(data.item.doc);
  return (
    <article className="reader" aria-label="Открытое письмо">
      <header className="reader-header">
        <button className="back" type="button" onClick={onClose}>
          ← К списку
        </button>
        <h2 ref={heading} tabIndex={-1}>
          {letter ? letter.subject || "Без темы" : "Письмо"}
        </h2>
        {letter && data && (
          <div className="reader-meta">
            <span className="sender-avatar" aria-hidden="true">
              {letter.sender.slice(0, 1).toUpperCase() || "@"}
            </span>
            <div className="reader-address">
              <strong>{letter.sender || "Отправитель не указан"}</strong>
              {letter.recipient && <span>Кому: {letter.recipient}</span>}
            </div>
            <MessageDate value={data.item.doc_dt} />
          </div>
        )}
      </header>
      {pending && <Loading>Загружаем письмо…</Loading>}
      {error != null && <Failure error={error} retry={load} />}
      {letter && <div className="message-body">{letter.body}</div>}
    </article>
  );
}
