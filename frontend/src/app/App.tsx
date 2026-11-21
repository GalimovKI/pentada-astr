import { useEffect, useState } from "react";
import { api, type Context, type Features, type Mailboxes } from "../api/client";
import { Failure, Loading } from "../components/Status";
import { MailboxPicker } from "../features/mailboxes/MailboxPicker";
import { EvaluationPanel } from "../features/evaluations/EvaluationPanel";
import { MailSession } from "./MailSession";
import { useTask } from "./useTask";
import { validDate } from "./validation";

export function App() {
  const { data, pending, error, run } = useTask<Mailboxes>();
  const [box, setBox] = useState<Pick<Context, "mailbox" | "dataset">>({ mailbox: "" });
  const [date, setDate] = useState("2028-09-11");
  useEffect(() => {
    void run(api.mailboxes);
  }, [run]);
  const [mailModel, setMailModel] = useState("");
  const features = useTask<Features>();
  const { run: loadFeatures } = features;
  const [view, setView] = useState(window.location.hash);
  useEffect(() => {
    void loadFeatures(api.features);
    const update = () => setView(window.location.hash);
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, [loadFeatures]);
  const dev = features.data?.evaluations === true;
  const showEvaluation = dev && view === "#evaluations";
  const selected = box.mailbox || data?.items[0] || "";
  const dateValid = validDate(date);
  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href="#main">
          <span>
            Почта<span className="brand-subtitle">{dev ? "Dev-версия" : "Умный поиск"}</span>
          </span>
        </a>
      </header>
      {dev && (
        <nav className="dev-nav" aria-label="Вкладки dev-сайта">
          <a href="#main" aria-current={showEvaluation ? undefined : "page"}>Почта</a>
          <a href="#evaluations" aria-current={showEvaluation ? "page" : undefined}>Оценка моделей</a>
        </nav>
      )}
      {dev && <EvaluationPanel visible={showEvaluation} />}
      <main id="main" className="app-layout" hidden={showEvaluation}>
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
              boxes={data}
              mailbox={selected}
              dataset={box.dataset}
              onChange={setBox}
            />
          )}
          <div className="field">
            <label htmlFor="scenario-date">Почта на дату</label>
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
                ? "Это «сегодня» для ящика. Письма, полученные позже, скрыты."
                : "Укажите корректную дату в формате ГГГГ-ММ-ДД."}
            </p>
          </div>
          <div className="context-note">
            <span className="note-dot" aria-hidden="true" />
            {box.dataset ? "Архив EnronQA" : "Синтетические ящики"}
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
              Почта на <strong>{dateValid ? date : "не задана"}</strong>
            </span>
          </div>
          {selected && dateValid && data && (
            <MailSession
              key={JSON.stringify([box.dataset, selected, date])}
              context={{ mailbox: selected, date, dataset: box.dataset }}
              models={features.data?.mail_models}
              model={mailModel || features.data?.mail_models?.[0]?.id}
              onModelChange={setMailModel}
            />
          )}
          {!dateValid && (
            <div className="empty">
              <h2>Выберите дату просмотра</h2>
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
