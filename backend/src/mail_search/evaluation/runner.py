"""Validate rankings independently of the engine and compute local metrics."""

import json
import math
from pathlib import Path
from statistics import fmean
from time import perf_counter_ns

from ..core.errors import ValidationError
from ..domain.models import Query, SearchEngine
from ..ingestion.dataset import Dataset
from .metrics import metrics_at_k


def validate_ranking(dataset: Dataset, query: Query, ranking: list[str]) -> None:
    seen = set()
    for doc_id in ranking:
        if not isinstance(doc_id, str) or doc_id not in dataset.documents:
            raise ValidationError(f"{query.query_id}: unknown doc_id: {doc_id!r}")
        if doc_id in seen:
            raise ValidationError(f"{query.query_id}: duplicate doc_id: {doc_id}")
        seen.add(doc_id)
        document = dataset.documents[doc_id]
        if document.synthetic_user != query.synthetic_user:
            raise ValidationError(f"{query.query_id}: document from another mailbox: {doc_id}")
        if document.doc_dt is not None and document.doc_dt > query.query_date:
            raise ValidationError(f"{query.query_id}: document unavailable on query_date: {doc_id}")


def read_predictions(path: str | Path) -> dict[str, list[str]]:
    predictions = {}
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
            qid, ranking = row["query_id"], row["doc_ids"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ValidationError(f"predictions:{number}: expected query_id and doc_ids") from exc
        if not isinstance(qid, str) or not isinstance(ranking, list):
            raise ValidationError(f"predictions:{number}: expected string query_id and list doc_ids")
        if qid in predictions:
            raise ValidationError(f"predictions:{number}: duplicate query_id: {qid}")
        predictions[qid] = ranking
    return predictions


def run_engine(dataset: Dataset, engine: SearchEngine, k: int) -> tuple[dict, dict, dict]:
    predictions, durations, errors = {}, {}, {}
    for query in dataset.queries:
        request = query.request()
        start = perf_counter_ns()
        try:
            try:
                hits = list(engine.search(request, k))
            finally:
                durations[query.query_id] = (perf_counter_ns() - start) / 1_000_000
            if len(hits) > k:
                raise ValidationError(f"engine returned more than K={k} hits")
            ranking = [hit.doc_id for hit in hits]
            if any(not math.isfinite(hit.score) for hit in hits):
                raise ValidationError("engine returned a non-finite score")
            validate_ranking(dataset, query, ranking)
            predictions[query.query_id] = ranking
        except Exception as exc:
            # Failed queries remain in the macro-average with zero scores.
            errors[query.query_id] = f"{type(exc).__name__}: {exc}"
            predictions[query.query_id] = []
    return predictions, durations, errors


def evaluate(dataset: Dataset, predictions: dict[str, list[str]], ks: list[int],
             *, durations: dict | None = None, errors: dict | None = None) -> tuple[dict, list[dict]]:
    if not ks or any(type(k) is not int or k <= 0 for k in ks) or len(set(ks)) != len(ks):
        raise ValidationError("K values must be distinct positive integers")
    expected = {query.query_id for query in dataset.queries}
    missing, extra = expected - predictions.keys(), predictions.keys() - expected
    if missing or extra:
        raise ValidationError(f"prediction coverage mismatch: missing={sorted(missing)}, extra={sorted(extra)}")
    per_query = []
    for query in dataset.queries:
        ranking = predictions[query.query_id]
        validate_ranking(dataset, query, ranking)
        relevant = {did for did, score in dataset.qrels[query.query_id].items() if score > 0}
        per_query.append({
            "query_id": query.query_id, "synthetic_user": query.synthetic_user,
            "query_date": query.query_date.isoformat(), "query": query.query,
            "relevant_count": len(relevant), "retrieved_count": len(ranking),
            "relevant_doc_ids": sorted(relevant),
            "missed_doc_ids_at_max_k": sorted(relevant - set(ranking[:max(ks)])),
            "metrics": {str(k): metrics_at_k(ranking, dataset.qrels[query.query_id], k) for k in ks},
            "latency_ms": (durations or {}).get(query.query_id),
            "error": (errors or {}).get(query.query_id),
        })
    single = [row for row in per_query if row["relevant_count"] == 1]
    aggregate = {
        "queries": len(per_query), "failed_queries": len(errors or {}),
        "single_relevant_queries": len(single),
        "aggregation": "macro; no-relevant queries receive zero; failed queries retained",
        "by_k": {str(k): {
            **{metric: fmean(row["metrics"][str(k)][metric] for row in per_query)
               for metric in ("recall", "ndcg", "mrr")},
            "mrr_single": fmean(row["metrics"][str(k)]["mrr"] for row in single) if single else None,
        } for k in ks},
    }
    return aggregate, per_query


def format_report(run: dict, metrics: dict, per_query: list[dict]) -> str:
    lines = ["# Локальная оценка поиска", "", f"Статус: **{run['status']}**.", "",
             f"Движок: `{run.get('engine', 'external_predictions')}`.",
             f"Конфигурация: `{json.dumps(run.get('engine_config', {}), ensure_ascii=False, sort_keys=True)}`.",
             f"Fingerprint данных: `{run['dataset']['fingerprint']}`.",
             f"Fingerprint кода eval: `{run['code']['sha256']}`.",
             f"Запросов: {metrics['queries']}; ошибок: {metrics['failed_queries']}; "
             f"запросов с одним релевантным письмом: {metrics['single_relevant_queries']}.", "",
             "## Метрики", "", "| K | Recall@K | nDCG@K | MRR@K, все запросы | MRR@K, одно релевантное |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for k, values in metrics["by_k"].items():
        single = "—" if values["mrr_single"] is None else f"{values['mrr_single']:.6f}"
        lines.append(f"| {k} | {values['recall']:.6f} | {values['ndcg']:.6f} | {values['mrr']:.6f} | {single} |")
    lines += ["", "Макроусреднение; документы без строки qrels имеют оценку 0. "
              "Запросы без релевантных писем получают 0; ошибки не исключаются. "
              "K и правила усреднения — параметры локальной проверки, не официальный итоговый балл."]
    latency = run.get("engine_latency")
    if latency:
        lines += ["", "## Время", "", f"Построение движка: {run['engine_build_ms']:.2f} мс.",
                  f"Последовательный проход, {latency['samples']} вызовов, без отдельного прогрева.",
                  f"p50 / p95 / p99: {latency['p50']:.3f} / {latency['p95']:.3f} / {latency['p99']:.3f} мс.",
                  "Перцентили: nearest rank. Измерен только вызов движка в процессе, без построения индекса, "
                  "загрузки данных, проверки выдачи и расчёта метрик. Это не серверный p99 под нагрузкой."]
    elif "server_latency" in run:
        timing = run["server_latency"]
        p99 = "—" if timing["p99"] is None else f"{timing['p99']:.3f} мс"
        lines += ["", f"Серверный p99 по {timing['samples']} успешным запросам — {p99}.",
                  "Последовательный проход через API (ASGI), без отдельного прогрева."]
    else:
        lines += ["", "Время поиска для внешней выдачи не измерялось."]
    focus = "10" if "10" in metrics["by_k"] else str(max(map(int, metrics["by_k"])))
    lines += ["", f"## Запросы с наименьшим nDCG@{focus}", "",
              "| query_id | Recall | nDCG | Запрос |", "| --- | ---: | ---: | --- |"]
    for row in sorted(per_query, key=lambda r: (r["metrics"][focus]["ndcg"], r["query_id"]))[:10]:
        query = row["query"].replace("|", "\\|").replace("\n", " ")
        values = row["metrics"][focus]
        lines.append(f"| {row['query_id']} | {values['recall']:.4f} | {values['ndcg']:.4f} | {query} |")
    return "\n".join(lines) + "\n"


def write_run(output: Path, run: dict, metrics: dict, per_query: list[dict], predictions: dict) -> None:
    output.mkdir(parents=True, exist_ok=False)
    for name, value in (("run.json", run), ("metrics.json", metrics)):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for name, rows in (("per_query.jsonl", per_query), ("predictions.jsonl", [
            {"query_id": qid, "doc_ids": ranking} for qid, ranking in predictions.items()])):
        (output / name).write_text("".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows), encoding="utf-8")
    (output / "report.md").write_text(format_report(run, metrics, per_query), encoding="utf-8")
