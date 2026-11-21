import { useEffect, useState } from "react";
import {
  api,
  type Context,
  type Messages,
  type SearchResponse,
} from "../api/client";
import { useTask } from "./useTask";
import { SearchForm } from "../features/search/SearchForm";
import { MessageList } from "../features/messages/MessageList";
import { MessageReader } from "../features/messages/MessageReader";
import { Empty, Failure, Loading } from "../components/Status";

export function MailSession({ context }: { context: Context }) {
  const list = useTask<Messages>();
  const search = useTask<SearchResponse>();
  const [submitted, setSubmitted] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const { run: loadList } = list;
  useEffect(() => {
    void loadList((signal) => api.messages(context, signal));
  }, [context.mailbox, context.date, loadList]);

  function nextPage() {
    const cursor = list.data?.next_cursor;
    if (list.busy() || !cursor) return;
    void list.run((signal) => api.messages(context, signal, cursor), {
      keepData: true,
      merge: (previous, next) => ({
        ...next,
        items: [...(previous?.items ?? []), ...next.items],
      }),
    });
  }
  function find(query: string) {
    setSubmitted(query);
    setSelected(null);
    void search.run((signal) => api.search(context, query, signal));
  }
  function backToList() {
    search.reset();
    setSubmitted(null);
    setSelected(null);
  }
  function closeMessage() {
    const id = selected;
    setSelected(null);
    // Restore focus after the mobile list becomes visible again.
    requestAnimationFrame(() =>
      document.getElementById(`message-${id}`)?.focus(),
    );
  }
  const receiptDate = search.data?.receipt_date;
  const searching = submitted !== null;
  const task = searching ? search : list;
  const items = task.data?.items ?? [];
  return (
    <>
      <section className="search-area" aria-label="Поиск">
        <SearchForm onSearch={find} pending={search.pending} />
      </section>
      <div className={`mail-workspace ${selected ? "reading" : ""}`}>
        <section
          className="list-pane"
          aria-label={searching ? "Результаты поиска" : "Список писем"}
        >
          <header className="list-header">
            <div>
              <span className="eyebrow">
                {searching ? "По вашему запросу" : "Выбранный ящик"}
              </span>
              <h2>{searching ? "Результаты поиска" : "Все письма"}</h2>
            </div>
            {searching && (
              <button type="button" onClick={backToList}>
                Все письма
              </button>
            )}
          </header>
          {searching && <p className="submitted">«{submitted}»</p>}
          {searching && receiptDate && (
            <p className="receipt-date">Получено <time dateTime={receiptDate}>
              {new Date(receiptDate + "T00:00:00Z").toLocaleDateString("ru-RU", {
                day: "numeric", month: "long", year: "numeric", timeZone: "UTC",
              })}
            </time></p>
          )}
          <p className="list-caption">
            {items.length > 0
              ? `${searching ? "Найдено" : "Загружено"}: ${items.length}`
              : "Письма на выбранную дату"}
            {searching && " · В порядке релевантности"}
          </p>
          {task.pending && (
            <Loading>
              {searching
                ? "Выполняем поиск…"
                : list.data
                  ? "Загружаем следующую страницу…"
                  : "Загружаем письма…"}
            </Loading>
          )}
          {task.error != null && (
            <Failure
              error={task.error}
              retry={() =>
                searching
                  ? find(submitted)
                  : list.data
                    ? nextPage()
                    : void list.run((signal) => api.messages(context, signal))
              }
            />
          )}
          {task.data && !task.pending && items.length === 0 && (
            <Empty
              title={searching ? "Писем не найдено" : "Здесь пока нет писем"}
            >
              {searching
                ? "Попробуйте другие слова или проверьте дату просмотра."
                : "На выбранную дату в этом ящике нет доступных писем."}
            </Empty>
          )}
          <MessageList items={items} selected={selected} onOpen={setSelected} />
          {!searching && list.data?.next_cursor && (
            <div className="pagination">
              <button type="button" disabled={list.pending} onClick={nextPage}>
                Загрузить ещё
              </button>
            </div>
          )}
        </section>
        <section className="reader-pane" aria-label="Область чтения">
          {selected ? (
            <MessageReader
              key={selected}
              context={context}
              id={selected}
              passage={search.data?.items.find((item) => item.doc_id === selected)?.passage}
              onClose={closeMessage}
            />
          ) : (
            <Empty title="Выберите письмо">
              Откройте письмо из списка, чтобы прочитать полный исходный текст.
            </Empty>
          )}
        </section>
      </div>
    </>
  );
}
