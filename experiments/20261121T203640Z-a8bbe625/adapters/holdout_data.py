"""Build the holdout table only from validated common-eval artifacts."""
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
from statistics import fmean

HOLDOUT = Path("data/benchmarks/team-holdout-v1/eval")
RUN_ID = "20261121T203640Z-a8bbe625"
RUN = Path("reports/quality/runs") / RUN_ID
FINGERPRINT = "2fbf150de7ccbb001109a060c6036d33c8349d7e00fd01792c101cc7f699164e"
KS = ("1", "5", "10", "20", "50", "100")
SLICES = {
    "all": "Все запросы",
    "no_date": "Без даты",
    "event_date": "Дата события в письме",
    "status": "Статус действия",
    "receipt_day": "День получения",
    "receipt_range": "Диапазон получения",
}
EXTRA = {
    "e5-dev": ("semantic", "E5 · текущий dev", "ONNX INT8. Косинусный поиск по всем доступным письмам ящика."),
    "bm25-e5-rrf": ("hybrid", "BM25 + E5 через RRF", "Объединяет кандидатов двух поисков по обратным рангам."),
    "bm25-e5-minilm": ("hybrid", "BM25 + E5 → MiniLM", "MiniLM перевыставляет порядок кандидатов из объединённого списка BM25 и E5."),
    "minilm-all": ("semantic", "mMARCO MiniLM по всему ящику", "При отсутствии дня оценивает все доступные письма выбранного ящика."),
    "e5-enron": ("semantic", "E5 по полному запросу", "Проверяет сырую формулировку без очистки слов и без фильтра одного дня. Веса FP32 ONNX."),
    "bm25-raw-no-date": ("lexical", "Исходный BM25 без фильтра дня", "Сохраняет текст запроса и ограничения по ящику и дате сценария."),
    "stemmed-no-date": ("lexical", "BM25 со Snowball без фильтра дня", "Учитывает словоформы и оставляет в выдаче доступные письма других дней."),
    "improved-no-date": ("lexical", "Улучшенный BM25 без фильтра дня", "Стемминг, статистика корпуса и сниженный вес вводных слов."),
    "soft-llm-date": ("metadata", "E5 + дата по Qwen", "Применяет мягкий бонус только к распознанной дате получения."),
    "soft-llm-people": ("metadata", "E5 + участники по Qwen", "Применяет мягкий бонус только к распознанному отправителю или адресату."),
    "rrf-enron-e5-bm25": ("hybrid", "E5 + BM25 без фильтра дня, RRF", "Объединяет первые 100 результатов двух веток с равными весами."),
}
ENRON_EXTRA = (
    "e5-focus", "e5-qwen-only", "rrf-rubert-bm25", "rrf-e5-passages-bm25", "rrf-e5-doc2query-bm25",
    "minilm-top20", "minilm-e5-top20", "minilm-bm25-top20", "minilm-doc2query-top20",
)
METHOD_NOTES = {
    "date": "Пустая выдача без распознанного дня. Контроль применим к 4 из 60 формулировок.",
    "minilm": "Пустая выдача без распознанного дня. Контроль применим к 4 из 60 формулировок.",
    "minilm-all": "Для широкого поиска сравнение проводилось без отбора кандидатов BM25.",
    "e5-focus": "Локальная адаптация признака «тема и начало», первые 500 символов. Использован ONNX FP32.",
    "e5-enron": "Локальная репродукция с ONNX FP32 вместо варианта PyTorch.",
    "bm25-e5-minilm": "Архивная реализация увеличивает пул реранжирования при K=100. Штатный MiniLM 75/25 использует 20 кандидатов.",
    "rrf-rubert-bm25": "Локальный вариант использует распознавание дня из исходного эксперимента RuBERT.",
    "rrf-e5-passages-bm25": "Ветка по фрагментам распознаёт день. В ветке BM25 фильтр дня отключён.",
}
FAMILY_ALIASES = {"dense": "semantic", "rerank": "hybrid"}


def rows(file):
    return [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines()]


def split(meta):
    if meta["slice"] != "receipt_period":
        return meta["slice"]
    return "receipt_day" if meta["received_from"] == meta["received_to"] else "receipt_range"


def load_method(folder, groups, ids):
    run = json.loads((folder / "run.json").read_text())
    metrics = json.loads((folder / "metrics.json").read_text())
    assert run["dataset"]["fingerprint"] == FINGERPRINT
    assert run["ks"] == list(map(int, KS)) and metrics["queries"] == len(ids)
    assert metrics["failed_queries"] == 0 and run["status"] in {"ok", "completed"}
    items = {row["query_id"]: row for row in rows(folder / "per_query.jsonl")}
    assert set(items) == ids and not any(row["error"] for row in items.values())
    splits = {}
    for label, qids in groups.items():
        singles = [qid for qid in qids if items[qid]["relevant_count"] == 1]
        by_k = {}
        for k in KS:
            by_k[k] = {
                name: fmean(items[qid]["metrics"][k][name] for qid in qids)
                for name in ("recall", "ndcg", "mrr")
            }
            by_k[k]["mrr_single"] = (
                fmean(items[qid]["metrics"][k]["mrr"] for qid in singles) if singles else None
            )
        splits[label] = by_k
    assert splits["all"] == metrics["by_k"]
    return splits


def holdout_data(baselines, enron):
    raw = (HOLDOUT / "queries_dev.jsonl").read_bytes()
    qrels = (HOLDOUT / "qrels_dev.jsonl").read_bytes()
    manifest = json.loads((HOLDOUT / "manifest.json").read_text())
    for name, payload in (("queries_dev.jsonl", raw), ("qrels_dev.jsonl", qrels)):
        assert manifest["sha256"][name] == sha256(payload).hexdigest()
    ids = set()
    groups = defaultdict(list)
    qrels_counts = Counter(row["query_id"] for row in map(json.loads, qrels.splitlines()))
    metadata = {item["query_id"]: item for item in rows(HOLDOUT / "slices.jsonl")}
    mailbox_labels = {box: f"Ящик {i}" for i, box in enumerate(
        sorted({row["synthetic_user"] for row in map(json.loads, raw.splitlines())}), 1
    )}
    queries = []
    for query in map(json.loads, raw.splitlines()):
        qid = query["query_id"]
        assert qid not in ids
        ids.add(qid)
        scenario = split(metadata[qid])
        groups["all"].append(qid)
        groups[scenario].append(qid)
        queries.append({
            "id": qid.rsplit("-", 1)[1], "text": query["query"], "asOf": query["query_date"],
            "mailbox": mailbox_labels[query["synthetic_user"]], "slice": scenario, "relevant": qrels_counts[qid],
        })
    assert len(ids) == 60 and len(mailbox_labels) == 5 and sum(qrels_counts.values()) == 222
    assert set(metadata) == ids == set(qrels_counts)
    registry = [
        (item["id"], item["family"], item["name"], item["idea"]) for item in baselines["methods"]
    ]
    registry.extend((key, *value) for key, value in EXTRA.items())
    for key in ENRON_EXTRA:
        item = enron["models"][key]
        registry.append((key, FAMILY_ALIASES.get(item["family"], item["family"]), item["name"], item["idea"]))
    methods, unavailable = [], []
    for key, family, name, idea in registry:
        folder = RUN / key
        if not (folder / "metrics.json").is_file():
            unavailable.append({"id": key, "name": name})
            continue
        methods.append({"id": key, "family": family, "name": name, "idea": idea,
                        "note": METHOD_NOTES.get(key), "scores": load_method(folder, groups, ids)})
    diagnostics = json.loads((RUN.parent / "20261121T201426Z-841b6b1d/slices.json").read_text())
    return {
        "slices": {key: {"label": label, "count": len(groups[key])} for key, label in SLICES.items()},
        "queries": queries,
        "methods": methods,
        "unavailable": unavailable,
        "families": baselines["families"],
        "fingerprint": FINGERPRINT,
        "links": {
            "experiment": f"https://github.com/GalimovKI/pentada-astr/tree/team-memory/experiments/{RUN_ID}",
            "base": "team-holdout-v1.md",
        },
        "outOfWindow": diagnostics["methods"]["status"]["receipt_range_top10_out_of_range"],
        "rangeTotal": diagnostics["methods"]["status"]["receipt_range_top10_returned"],
    }
