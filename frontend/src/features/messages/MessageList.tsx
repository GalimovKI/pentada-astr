import { parseLetter } from "./parseLetter";
import type { Preview } from "../../api/client";
import { MessageDate } from "../../components/Status";

export function MessageList({
  items,
  selected,
  onOpen,
}: {
  items: Preview[];
  selected: string | null;
  onOpen: (id: string) => void;
}) {
  return (
    <ol className="message-list" aria-label="Письма">
      {items.map((item) => {
        const { sender, subject, body } = parseLetter(item.snippet);
        return (
          <li key={item.doc_id}>
            <button
              type="button"
              id={`message-${item.doc_id}`}
              className={`message-card ${selected === item.doc_id ? "selected" : ""}`}
              aria-pressed={selected === item.doc_id}
              onClick={() => onOpen(item.doc_id)}
            >
              <span className="card-meta">
                <strong className="list-sender">{sender}</strong>
                <MessageDate value={item.doc_dt} />
              </span>
              <span className="list-subject">{subject || body || "Без темы"}</span>
              {subject && body && <span className="snippet">{body}</span>}
            </button>
          </li>
        );
      })}
    </ol>
  );
}
