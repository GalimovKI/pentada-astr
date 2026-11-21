import { parseLetter } from "./parseLetter";
import { HighlightedText } from "./HighlightedText";
import type { Preview, Hit } from "../../api/client";
import { MessageDate } from "../../components/Status";

export function MessageList({
  items,
  selected,
  onOpen,
}: {
  items: (Preview | Hit)[];
  selected: string | null;
  onOpen: (id: string) => void;
}) {
  return (
    <ol className="message-list" aria-label="Письма">
      {items.map((item) => {
        const { sender, subject, body } = parseLetter(item.snippet);
        const passage = "passage" in item ? item.passage : null;
        return (
          <li key={item.doc_id}>
            <button
              type="button"
              id={`message-${item.doc_id}`}
              className={`message-card ${selected === item.doc_id ? "selected" : ""}`}
              aria-pressed={selected === item.doc_id}
              onClick={() => onOpen(item.doc_id)}
            >
              <span className="list-avatar" aria-hidden="true">
                {sender ? (sender.startsWith("mail-") ? "@" : sender[0].toUpperCase()) : <span className="envelope" />}
              </span>
              <span className="card-meta">
                <strong className="list-sender">{sender || "Отправитель не указан"}</strong>
                <MessageDate value={item.doc_dt} />
              </span>
              <span className="list-subject">{subject || (passage ? "Без темы" : body) || "Без темы"}</span>
              {passage ? (
                <span className="snippet matched-snippet">
                  <HighlightedText text={passage.text} offset={passage.offset} passage={passage} />
                </span>
              ) : subject && body && <span className="snippet">{body}</span>}
            </button>
          </li>
        );
      })}
    </ol>
  );
}
