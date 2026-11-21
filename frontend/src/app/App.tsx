import { useEffect, useState } from "react";
import { api, type Mailboxes } from "../api/client";
import { Failure, Loading } from "../components/Status";
import { MailboxPicker } from "../features/mailboxes/MailboxPicker";
import { MailSession } from "./MailSession";
import { useTask } from "./useTask";
import { validDate } from "./validation";

export function App() {
  const { data, pending, error, run } = useTask<Mailboxes>();
  const [mailbox, setMailbox] = useState("");
  const [date, setDate] = useState("2028-09-11");
  useEffect(() => {
    void run(api.mailboxes);
  }, [run]);
  const selected = mailbox || data?.items[0] || "";
  const dateValid = validDate(date);
  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href="#main">
          <span>
            Почта<span className="brand-subtitle">Умный поиск</span>
          </span>
        </a>
      </header>
      <main id="main" className="app-layout">
        <aside className="sidebar" aria-label="Контекст сценария">
          <div>
            <span className="eyebrow">Почта</span>
            <h1>Мой ящик</h1>
            <p className="sidebar-intro">Все письма и умный поиск</p>
          </div>
          {pending && <Loading>Загружаем ящики…</Loading>}
          {error != null && (
            <Failure error={error} retry={() => void run(api.mailboxes)} />
          )}
          {data && data.items.length === 0 && (
            <p role="status">Нет доступных ящиков.</p>
          )}
          {data && data.items.length > 0 && (
            <MailboxPicker
              items={data.items}
              value={selected}
              onChange={setMailbox}
            />
          )}
          <div className="field">
            <label htmlFor="scenario-date">Дата сценария</label>
            <input
              id="scenario-date"
              type="date"
              value={date}
              aria-invalid={!dateValid}
              aria-describedby="date-help"
              onChange={(event) => setDate(event.target.value)}
            />
            <p
              id="date-help"
              className={dateValid ? "hint" : "validation"}
              role={dateValid ? undefined : "alert"}
            >
              {dateValid
                ? "Поиск и просмотр выполняются относительно этой даты. Будущие письма скрыты."
                : "Укажите корректную дату в формате ГГГГ-ММ-ДД."}
            </p>
          </div>
          <div className="context-note">
            <span className="note-dot" aria-hidden="true" />
            Синтетические ящики
            <p>
              Выбор ящика задаёт контекст демонстрации. Вход в реальную почту не
              требуется.
            </p>
          </div>
        </aside>
        <div className="content">
          <div className="context-bar">
            <span>Почтовый архив</span>
            <span>
              Дата сценария: <strong>{dateValid ? date : "не задана"}</strong>
            </span>
          </div>
          {selected && dateValid && data && (
            <MailSession
              key={JSON.stringify([selected, date])}
              context={{ mailbox: selected, date }}
            />
          )}
          {!dateValid && (
            <div className="empty">
              <h2>Задайте дату сценария</h2>
              <p>
                Выберите дату, чтобы просматривать письма и искать в архиве.
              </p>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
