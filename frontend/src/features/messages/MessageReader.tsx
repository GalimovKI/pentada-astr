import { HighlightedText } from "./HighlightedText";
import { parseLetter } from "./parseLetter";
import { useEffect, useRef } from "react";
import { api, type Context, type Passage, type MessageResponse } from "../../api/client";
import { useTask } from "../../app/useTask";
import { Failure, Loading, MessageDate } from "../../components/Status";

export function MessageReader({
  context,
  id,
  passage,
  onClose,
}: {
  context: Context;
  id: string;
  passage?: Passage | null;
  onClose: () => void;
}) {
  const { data, pending, error, run } = useTask<MessageResponse>();
  const heading = useRef<HTMLHeadingElement>(null);
  const reader = useRef<HTMLElement>(null);
  const load = () => void run((signal) => api.message(context, id, signal));
  useEffect(() => {
    void run((signal) => api.message(context, id, signal));
    heading.current?.focus({ preventScroll: true });
    if (window.matchMedia("(max-width: 700px)").matches)
      reader.current?.scrollIntoView({ block: "start" });
    else if (reader.current?.parentElement)
      reader.current.parentElement.scrollTop = 0;
  }, [context.mailbox, context.date, id, run]);
  const letter = data && parseLetter(data.item.doc);
  useEffect(() => {
    if (data && passage)
      reader.current?.querySelector("mark")?.scrollIntoView({ block: "nearest" });
  }, [data, passage]);
  function field(name: "sender" | "subject" | "recipient" | "body") {
    return letter && <HighlightedText text={letter[name]} offset={letter.offsets[name]} passage={passage} />;
  }
  return (
    <article ref={reader} className="reader" aria-label="Открытое письмо">
      <header className="reader-header">
        <button className="back" type="button" onClick={onClose}>
          ← К списку
        </button>
        <h2 ref={heading} tabIndex={-1}>
          {letter ? (letter.subject ? field("subject") : "Без темы") : "Письмо"}
        </h2>
        {letter && data && (
          <div className="reader-meta">
            <span className="sender-avatar" aria-hidden="true">
              {letter.sender.slice(0, 1).toUpperCase() || "@"}
            </span>
            <div className="reader-address">
              <strong>{letter.sender ? field("sender") : "Отправитель не указан"}</strong>
              {letter.recipient && <span>Кому: {field("recipient")}</span>}
            </div>
            <MessageDate value={data.item.doc_dt} />
          </div>
        )}
      </header>
      {pending && <Loading>Загружаем письмо…</Loading>}
      {error != null && <Failure error={error} retry={load} />}
      {letter && <div className="message-body">{field("body")}</div>}
    </article>
  );
}
