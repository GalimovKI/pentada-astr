import { useEffect, useState } from "react";
import { api, type EvalDevice, type EvaluationCatalog } from "../../api/client";
import { useTask } from "../../app/useTask";
import { Failure } from "../../components/Status";

const decimal = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 4 });

const quantiles = ["p50", "p90", "p95", "p99"] as const;
const devices = { cpu: "CPU", cuda: "GPU (CUDA)" };

function MetricValue({ value, max = 1 }: { value: number | null; max?: number }) {
  if (value == null) return <>—</>;
  return <span className="metric-score">
    <span>{decimal.format(value)}</span>
    <meter aria-hidden="true" min={0} max={max} value={value} />
  </span>;
}

export function EvaluationPanel({ visible }: { visible: boolean }) {
  const { data, error, pending, run } = useTask<EvaluationCatalog>();
  const [model, setModel] = useState("");
  const [dataset, setDataset] = useState("");
  const [device, setDevice] = useState<EvalDevice>();
  const current = data?.run;
  const active = current?.status === "running";
  const selectedModel = model || current?.model || data?.models[0]?.id || "";
  const selectedDataset = dataset || current?.dataset || data?.datasets[0]?.id || "";
  const options = data?.models.find(item => item.id === selectedModel)?.devices ?? ["cpu"];
  const preferredDevice = device ?? current?.device;
  const selectedDevice = preferredDevice && options.includes(preferredDevice) ? preferredDevice : options[0];
  const results = (data?.comparisons ?? []).filter(row => row.dataset === selectedDataset);
  const fingerprint = results.slice().sort((a, b) => b.created_at.localeCompare(a.created_at))[0]?.fingerprint;
  const comparison = results.filter(row => row.fingerprint === fingerprint).sort((a, b) => b.ndcg - a.ndcg);
  const maxLatency = Math.max(0, ...comparison.map(row => row.p99_ms ?? 0)) || 1;
  const refresh = () => void run(api.evaluations, { keepData: true });
  useEffect(() => {
    if (visible) void run(api.evaluations, { keepData: true });
  }, [visible, run]);
  useEffect(() => {
    if (!visible || !active || pending || error) return;
    const timer = window.setTimeout(() => void run(api.evaluations, { keepData: true }), 800);
    return () => clearTimeout(timer);
  }, [visible, active, pending, error, run, data]);
  return (
    <main className="eval-page" id="evaluations" hidden={!visible}>
      <h1>Оценка моделей</h1>
      <form className="eval-form" onSubmit={(event) => {
        event.preventDefault();
        if (!active && !pending && data)
          void run(signal => api.startEvaluation(selectedModel, selectedDataset, selectedDevice, signal), { keepData: true });
      }}>
        <label>Модель поиска<select value={selectedModel} onChange={e => setModel(e.target.value)} disabled={!data || active}>
          {data?.models.map(option => <option key={option.id} value={option.id}>{option.name}</option>)}
        </select></label>
        <label>Устройство<select value={selectedDevice} onChange={e => setDevice(e.target.value as EvalDevice)} disabled={!data || active || options.length === 1}>
          {options.map(id => <option key={id} value={id}>{devices[id]}</option>)}
        </select></label>
        <label>Датасет<select value={selectedDataset} onChange={e => setDataset(e.target.value)} disabled={!data || active}>
          {data?.datasets.map(option => <option key={option.id} value={option.id}>{option.name}</option>)}
        </select></label>
        <button type="submit" className="primary" disabled={!data || pending || active}>Запустить прогон</button>
      </form>
      {error != null && <Failure error={error} retry={refresh} />}
      {!data && pending && <p role="status">Загружаем список моделей…</p>}
      {data && comparison.length > 0 && <section className="eval-result">
        <h2>Сравнение моделей</h2>
        <p id="comparison-caption" className="hint">{data.datasets.find(option => option.id === selectedDataset)?.name} · последние успешные прогоны</p>
        <div className="eval-table" tabIndex={0} role="region" aria-label="Таблица сравнения"><table aria-labelledby="comparison-caption">
          <thead><tr><th>Модель</th><th>Устройство</th><th>Recall@10</th><th aria-sort="descending">nDCG@10 ↓</th><th>MRR@10</th>{quantiles.map(q => <th key={q} title="Длиннее полоса — больше задержка.">{q}, мс</th>)}<th>Место замера</th></tr></thead>
          <tbody>{comparison.map(row => <tr key={row.model + "/" + row.device}>
            <th scope="row">{data.models.find(option => option.id === row.model)?.name}</th>
            <td>{row.device ? devices[row.device] : "Не указано"}{row.precision && ` · ${row.precision}`}{row.rerank_depth && ` · топ-${row.rerank_depth}`}</td>
            {[row.recall, row.ndcg, row.mrr].map((value, i) =>
              <td key={i}><MetricValue value={value} /></td>)}
            {quantiles.map(q => <td key={q}><MetricValue value={row[`${q}_ms`] ?? null} max={maxLatency} /></td>)}
            <td>{row.source ?? "Этот стенд"}</td>
          </tr>)}</tbody>
        </table></div>
      </section>}
      {data && !comparison.length && <section className="eval-result">
        <h2>Сравнение моделей</h2>
        <p className="hint">Для этого датасета пока нет завершённых прогонов.</p>
      </section>}
      {data && current && current.dataset === selectedDataset && <section className="eval-result" aria-label="Результат прогона">
        <h2>{data.models.find(option => option.id === current.model)?.name}{current.device && ` · ${devices[current.device]}`}</h2>
        <p role="status">{current.phase}{current.total != null && ` · ${current.completed} из ${current.total} запросов`}</p>
        {active && <progress aria-label="Обработано запросов" max={current.total || 1} value={current.total ? current.completed : undefined} />}
        {current.metrics && <>
          <p>Ошибок: {current.metrics.failed_queries}. Запросов с одним релевантным письмом: {current.metrics.single_relevant_queries}.</p>
          <div className="eval-table"><table>
            <caption>Качество поиска по глубине выдачи</caption>
            <thead><tr><th>K</th><th>Recall@K</th><th>nDCG@K</th><th>MRR@K</th><th>MRR@K · одно письмо</th></tr></thead>
            <tbody>{Object.entries(current.metrics.by_k).map(([k, values]) =>
              <tr key={k}><th scope="row">{k}</th>{[values.recall, values.ndcg, values.mrr, values.mrr_single].map((value, i) =>
                <td key={i}><MetricValue value={value} /></td>)}</tr>)}</tbody>
          </table></div>
          <h3>Серверная задержка</h3>
          <p>{quantiles.map(q => {
            const ms = current[`${q}_ms`];
            return `${q} — ${ms == null ? "нет измерения" : decimal.format(ms) + " мс"}`;
          }).join(" · ")}</p>
          <p className="hint">Последовательные запросы через серверный API, до 100 результатов. Замер включает поиск и получение писем из базы, без сети и отрисовки. Измерений: {current.samples}.</p>
        </>}
      </section>}
    </main>
  );
}
