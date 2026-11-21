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
      {items.map((item, index) => (
        <li key={item.doc_id}>
          <button
            type="button"
            id={`message-${item.doc_id}`}
            className={`message-card ${selected === item.doc_id ? "selected" : ""}`}
            aria-pressed={selected === item.doc_id}
            onClick={() => onOpen(item.doc_id)}
          >
            <span className="card-meta">
              <span className="ordinal" aria-hidden="true">
                {String(index + 1).padStart(2, "0")}
              </span>
              <MessageDate value={item.doc_dt} />
            </span>
            <span className="snippet">
              {item.snippet || "Фрагмент текста отсутствует"}
            </span>
            <span className="doc-id">{item.doc_id}</span>
          </button>
        </li>
      ))}
    </ol>
  );
}
