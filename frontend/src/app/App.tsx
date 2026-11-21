import { useEffect, useState } from "react";
import { api, type Context, type Features, type Mailboxes } from "../api/client";
import { Failure, Loading } from "../components/Status";
import { MailboxPicker } from "../features/mailboxes/MailboxPicker";
import { EvaluationPanel } from "../features/evaluations/EvaluationPanel";
import { MailSession } from "./MailSession";
import { useTask } from "./useTask";
import { validDate } from "./validation";
import smartmailLogo from "../assets/smartmail-logo-vk.png";

export function App() {
  const { data, pending, error, run } = useTask<Mailboxes>();
  const [box, setBox] = useState<Pick<Context, "mailbox" | "dataset">>({ mailbox: "" });
  const [chosenDate, setDate] = useState<string | null>(null);
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
  const archive = data?.archives?.find(item => item.id === box.dataset);
  const selected = archive?.mailbox ?? (box.mailbox || data?.items[0] || "");
  const dateCorpus = archive ?? data?.archives?.find(item => item.id === "mail-public");
  const date = chosenDate ?? dateCorpus?.latest_date ?? "2028-09-11";
  const dateValid = validDate(date);
  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href="#main">
          {dev ? (
            <>
              <img className="brand-logo" src={smartmailLogo} alt="smartmail" width="1881" height="408" />
              <span className="brand-subtitle">Dev-версия</span>
            </>
          ) : (
            <span>Почта<span className="brand-subtitle">Умный поиск</span></span>
          )}
        </a>
        {dev && (
          <nav className="dev-nav" aria-label="Вкладки dev-сайта">
            <a href="#main" aria-current={showEvaluation ? undefined : "page"}>Почта</a>
            <a href="#evaluations" aria-current={showEvaluation ? "page" : undefined}>Оценка моделей</a>
          </nav>
        )}
      </header>
      {dev && <EvaluationPanel visible={showEvaluation} />}
      <main id="main" className="app-layout" hidden={showEvaluation}>
        <section className="mail-context" aria-label="Контекст сценария">
          <h1>Почтовый архив</h1>
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
              dataset={archive?.id}
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
              className={dateValid ? "sr-only" : "validation"}
              role={dateValid ? undefined : "alert"}
            >
              {dateValid
                ? "Показаны письма, доступные на эту дату."
                : "Укажите корректную дату в формате ГГГГ-ММ-ДД."}
            </p>
          </div>
        </section>
        <div className="content">
          {selected && dateValid && data && (
            <MailSession
              key={JSON.stringify([archive?.id, selected, date])}
              context={{ mailbox: selected, date, dataset: archive?.id }}
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
