import { useState, type ReactNode } from "react";
import { api, type Context, type SearchResponse } from "../api/client";
import smartmailLogo from "../assets/smartmail-logo-vk.png";
import { Empty, Failure, Loading } from "../components/Status";
import { MessageList } from "../features/messages/MessageList";
import { MessageReader } from "../features/messages/MessageReader";
import { SearchForm } from "../features/search/SearchForm";
import type { MailboxOption } from "./publicMailboxes";
import { useTask } from "./useTask";
import { queryError } from "./validation";

export function MailSession({ context, mailboxes, onMailboxChange, children }: {
  context?: Context;
  mailboxes: MailboxOption[];
  onMailboxChange: (id: string) => void;
  children: ReactNode;
}) {
  const search = useTask<SearchResponse>();
  const [draft, setDraft] = useState("");
  const [invalid, setInvalid] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const current = mailboxes.find(box => box.id === context?.mailbox);

  function find(query: string, scope = context) {
    const issue = queryError(query);
    setInvalid(issue);
    if (!scope || issue) return;
    setSubmitted(query);
    setSelected(null);
    void search.run(signal => api.search(scope, query, signal));
  }
  function switchMailbox(id: string) {
    if (!context || id === context.mailbox) return;
    onMailboxChange(id);
    if (submitted !== null) find(submitted, { ...context, mailbox: id });
  }
  function clear() {
    search.reset();
    setDraft("");
    setSubmitted(null);
    setSelected(null);
    setInvalid(null);
    document.getElementById("query")?.focus();
  }
  function closeMessage() {
    const id = selected;
    setSelected(null);
    requestAnimationFrame(() => document.getElementById(`message-${id}`)?.focus());
  }
  const items = search.data?.items ?? [];
  const receiptDate = search.data?.receipt_date;
  return (
    <main className={submitted === null ? "landing" : undefined}>
      <header className="search-panel">
        <h1><img className="brand-logo" src={smartmailLogo} alt="SmartMail" width="1881" height="408" /></h1>
        <div className="search-controls">
          {context && <div className="mailbox-picker">
            <label htmlFor="mailbox">Почтовый ящик</label>
            <select id="mailbox" value={context.mailbox} onChange={event => switchMailbox(event.target.value)}>
              {!current && <option value={context.mailbox} hidden>{context.mailbox}</option>}
              {mailboxes.map(box => <option key={box.id} value={box.id}>{box.name}</option>)}
            </select>
          </div>}
          <SearchForm value={draft} error={invalid} ready={Boolean(context)} example={current?.example}
            onChange={value => { setDraft(value); setInvalid(null); }}
            onSubmit={() => find(draft)} />
        </div>
      </header>
      {children}
      {submitted !== null && (
        <section className="search-results" aria-labelledby="results-title">
          <header className="results-heading">
            <h2 id="results-title">Результаты поиска</h2>
            <button type="button" onClick={clear}>Очистить поиск</button>
          </header>
          <p className="submitted">«{submitted}»</p>
          {receiptDate && <p className="receipt-date">Получено <time dateTime={receiptDate}>
            {new Date(receiptDate + "T00:00:00Z").toLocaleDateString("ru-RU", { timeZone: "UTC" })}
          </time></p>}
          {search.pending && <Loading>Выполняем поиск…</Loading>}
          {search.error != null && <Failure error={search.error} retry={() => find(submitted)} />}
          {search.data && (
            items.length === 0 ? <Empty title="Писем не найдено">Попробуйте другие слова.</Empty> : (
              <div className={`mail-workspace${selected ? " reading" : ""}`}>
                <div className="list-pane"><MessageList items={items} selected={selected} onOpen={setSelected} /></div>
                {selected && context && <section className="reader-pane" aria-label="Область чтения">
                  <MessageReader key={selected} context={context} id={selected}
                    passage={items.find(item => item.doc_id === selected)?.passage} onClose={closeMessage} />
                </section>}
              </div>
            )
          )}
        </section>
      )}
    </main>
  );
}
