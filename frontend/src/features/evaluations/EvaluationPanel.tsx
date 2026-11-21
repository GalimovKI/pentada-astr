import { useEffect, useState } from "react";
import { api, type EvaluationCatalog } from "../../api/client";
import { useTask } from "../../app/useTask";
import { Failure } from "../../components/Status";

const decimal = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 4 });

export function EvaluationPanel() {
  const { data, error, pending, run } = useTask<EvaluationCatalog>();
  const [model, setModel] = useState("");
  const [dataset, setDataset] = useState("");
  const current = data?.run;
  const active = current?.status === "running";
  const selectedModel = model || current?.model || data?.models[0]?.id || "";
  const selectedDataset = dataset || current?.dataset || data?.datasets[0]?.id || "";
  const refresh = () => void run(api.evaluations, { keepData: true });
  useEffect(() => { void run(api.evaluations); }, [run]);
  useEffect(() => {
    if (!active || pending || error) return;
    const timer = window.setTimeout(() => void run(api.evaluations, { keepData: true }), 800);
    return () => clearTimeout(timer);
  }, [active, pending, error, run, data]);
  return (
    <main className="eval-page" id="evaluations">
      <h1>Оценка моделей</h1>
      <form className="eval-form" onSubmit={(event) => {
        event.preventDefault();
        if (!active && !pending && data)
          void run(signal => api.startEvaluation(selectedModel, selectedDataset, signal), { keepData: true });
      }}>
        <label>Модель поиска<select value={selectedModel} onChange={e => setModel(e.target.value)} disabled={!data || active}>
          {data?.models.map(option => <option key={option.id} value={option.id}>{option.name}</option>)}
        </select></label>
        <label>Датасет<select value={selectedDataset} onChange={e => setDataset(e.target.value)} disabled={!data || active}>
          {data?.datasets.map(option => <option key={option.id} value={option.id}>{option.name}</option>)}
        </select></label>
        <button type="submit" className="primary" disabled={!data || pending || active}>Запустить прогон</button>
      </form>
      {error != null && <Failure error={error} retry={refresh} />}
      {!data && pending && <p role="status">Загружаем список моделей…</p>}
      {data && current && <section className="eval-result" aria-label="Результат прогона">
        <h2>{data.models.find(option => option.id === current.model)?.name}</h2>
        <p role="status">{current.phase}{current.total != null && ` · ${current.completed} из ${current.total} запросов`}</p>
        {active && <progress aria-label="Обработано запросов" max={current.total || 1} value={current.total ? current.completed : undefined} />}
        {current.metrics && <>
          <p>Ошибок: {current.metrics.failed_queries}. Запросов с одним релевантным письмом: {current.metrics.single_relevant_queries}.</p>
          <div className="eval-table"><table>
            <caption>Качество поиска по глубине выдачи</caption>
            <thead><tr><th>K</th><th>Recall@K</th><th>nDCG@K</th><th>MRR@K</th><th>MRR@K · одно письмо</th></tr></thead>
            <tbody>{Object.entries(current.metrics.by_k).map(([k, values]) =>
              <tr key={k}><th scope="row">{k}</th>{[values.recall, values.ndcg, values.mrr, values.mrr_single].map((value, i) =>
                <td key={i}>{value == null ? "—" : decimal.format(value)}</td>)}</tr>)}</tbody>
          </table></div>
          <h3>Серверная задержка p99</h3>
          <p>{current.p99_ms == null ? "Нет измерений" : `${decimal.format(current.p99_ms)} мс`} · целевой порог &lt; 1 000 мс</p>
          <p className="hint">Последовательные запросы через серверный API, до 100 результатов. Замер включает поиск и получение писем из базы, без сети и отрисовки. Измерений: {current.samples}.</p>
        </>}
      </section>}
    </main>
  );
}
