"""Run fixed report baselines on the frozen mailbox holdout with the common evaluator."""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import platform
import sqlite3
import sys

import numpy as np

from mail_search.core.provenance import code_version
from mail_search.domain.models import SearchHit, SearchRequest
from mail_search.evaluation.runner import evaluate, read_predictions, run_engine, write_run
from mail_search.ingestion.dataset import load_dataset
from mail_search.indexing.text import normalize, tokenize_stemmed
from mail_search.search import bm25, e5, event_aware, fuzzy
from mail_search.search.bm25_minilm import MiniLM, create_engine as minilm_engine
from mail_search.search.dates import receipt_day

from itertools import pairwise
import re

WORK = Path(__file__).resolve().parent
SOURCES = WORK / "sources"
DATASET = Path("data/benchmarks/team-holdout-v1/eval")
ORIGINAL = Path("reports/quality/runs/20261121T201426Z-841b6b1d")
MODEL_HOME = Path("artifacts/models")
FP32 = MODEL_HOME / "hybrid/e5"
FP32_INDEX = Path("artifacts/indexes/hybrid-e5-participants.npz")
FINGERPRINT = "2fbf150de7ccbb001109a060c6036d33c8349d7e00fd01792c101cc7f699164e"
HISTORICAL_E5 = "cedfd376aa32b88eb49f7b3654cc4b3c5822b20a"
SOFT = "33c38c4e8561faeeac973aa9f91a3248ada7742e"
HYBRID = "c14c9c230cef321278796ecb9fe60711a9366513"
KS = [1, 5, 10, 20, 50, 100]
STOPWORDS = frozenset("и или в во на о об обо с со из по к у для от за а про".split())
SENTENCE = re.compile(r"(?<=[.!?;])\s+|\r?\n+")

sys.path.insert(0, str(SOURCES / "e5"))
sys.path.insert(0, str(SOURCES / "soft"))
import mail_search.search as search_package
search_package.__path__.append(str(SOURCES / "hybrid"))


class Search:
    def __init__(self, search):
        self.search = search


class Prototype:
    def __init__(self, documents, encoder=None, vectors=None):
        from mailsearch.search import SearchEngine

        with sqlite3.connect(":memory:") as db:
            db.row_factory = sqlite3.Row
            db.execute("CREATE TABLE index_info (key TEXT, value TEXT)")
            db.execute("CREATE TABLE mail (doc_id TEXT, box TEXT, received TEXT, body TEXT, embedding BLOB)")
            metadata = {"count": str(len(documents)), "encoder": encoder.key if encoder else ""}
            db.executemany("INSERT INTO index_info VALUES (?, ?)", metadata.items())
            db.executemany(
                "INSERT INTO mail VALUES (?, ?, ?, ?, ?)",
                [(doc.doc_id, doc.synthetic_user, doc.doc_dt.isoformat() if doc.doc_dt else None,
                  doc.doc, vectors[i].tobytes() if vectors is not None else b"")
                 for i, doc in enumerate(documents)],
            )
            self.engine = SearchEngine(db, encoder)

    def mode(self, method):
        def search(query, k):
            ranked, _ = self.engine.search(query.query, query.synthetic_user, query.query_date, k, method)
            return [SearchHit(doc, 1 / rank) for rank, doc in enumerate(ranked, 1)]
        return Search(search)


class EncoderAdapter:
    def __init__(self, path=FP32):
        from mailsearch.encoder import encoder_key

        self.model = e5.encoder(path)
        self.key = encoder_key("e5") + ":onnx-fp32"
        self.dimensions = 384

    def encode(self, texts, *, query=False):
        prefix = "query: " if query else "passage: "
        return self.model.encode([prefix + text for text in texts])


def read_json(path):
    return json.loads(Path(path).read_text())


def run_model(dataset, method, engine, config, source):
    output = WORK / method
    if output.exists():
        run = read_json(output / "run.json")
        assert run["dataset"]["fingerprint"] == FINGERPRINT
        return read_predictions(output / "predictions.jsonl")
    pred, timing, errors = run_engine(dataset, engine, max(KS))
    return score_predictions(dataset, method, pred, config, source, timing, errors)


def score_predictions(dataset, method, predictions, config, source, timing=None, errors=None):
    output = WORK / method
    if output.exists():
        return read_predictions(output / "predictions.jsonl")
    metrics, items = evaluate(dataset, predictions, KS, durations=timing, errors=errors)
    run = {
        "format_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": dataset.summary, "python": platform.python_version(),
        "platform": platform.platform(), "machine": platform.machine(), "ks": KS, "source": DATASET.name,
        "engine": method, "engine_config": config, "source_code_ref": source,
        "code": code_version(sys.modules[__name__]), "status": "failed" if errors else "completed",
    }
    write_run(output, run, metrics, items, predictions)
    print(method, metrics["by_k"]["10"], "errors", metrics["failed_queries"], flush=True)
    if errors:
        raise ValueError(f"{method} had {len(errors)} errors; inspect {output / 'per_query.jsonl'}")
    return predictions


def box_documents(documents):
    boxes = defaultdict(list)
    for doc in documents:
        boxes[doc.synthetic_user].append(doc)
    return boxes


def day_candidates(boxes, request):
    day, query = receipt_day(request.query, request.query_date)
    docs = [doc for doc in boxes[request.synthetic_user]
            if (doc.doc_dt is None or doc.doc_dt <= request.query_date) and (day is None or doc.doc_dt == day)]
    return day, query.strip(" ,.!?;:"), docs


def proximity_engine(documents, lexical):
    texts = {doc.doc_id: doc.doc for doc in documents}
    sentences = {}

    def nearby_pairs(doc_id, wanted):
        if doc_id not in sentences:
            sentences[doc_id] = [tokenize_stemmed(line) for line in SENTENCE.split(texts[doc_id])]
        terms = set().union(*wanted)
        found = set()
        for sentence in sentences[doc_id]:
            locations = [(pos, token) for pos, token in enumerate(sentence) if token in terms]
            start = 0
            for pos, token in locations:
                while pos - locations[start][0] > 8:
                    start += 1
                for other_pos, other_term in locations[start:]:
                    if other_pos == pos:
                        break
                    pair = frozenset((other_term, token))
                    if pair in wanted:
                        found.add(pair)
                if found == wanted:
                    return 1.0
        return len(found) / len(wanted)

    def search(request, k):
        candidates = lexical.search(request, max(k, 100))
        _, text = receipt_day(request.query, request.query_date)
        text = bm25.MAIL_INTRO.sub("", bm25.LEADING_COMMAND.sub("", normalize(text), count=1), count=1)
        terms = [term for term in tokenize_stemmed(text) if term not in STOPWORDS]
        pairs = {frozenset((a, b)) for a, b in pairwise(terms) if a != b}
        if not candidates or not pairs or candidates[0].score <= 0:
            return candidates[:k]
        top = candidates[0].score
        hits = [SearchHit(hit.doc_id, hit.score / top + 0.08 * nearby_pairs(hit.doc_id, pairs))
                for hit in candidates]
        return sorted(hits, key=lambda hit: (-hit.score, hit.doc_id))[:k]

    return Search(search)


def lexical_suite(dataset, documents):
    stem = read_json("configs/search/bm25-stemmed.json")
    improved = read_json("configs/search/bm25-improved.json")
    variants = {
        "bm25-raw": read_json("configs/search/bm25.json"),
        "stemmed": stem,
        "corpus": stem | {"statistics_scope": "corpus"},
        "wrapper": stem | {"query_wrapper_weight": 0.1},
        "improved": improved,
    }
    for name, config in variants.items():
        run_model(dataset, name, bm25.create_engine(documents, config), config, "ea8c2f4")
    for name, weight in (("fuzzy-exact", 0.0), ("fuzzy", 1.4)):
        config = {"fuzzy_weight": weight}
        run_model(dataset, name, fuzzy.create_engine(documents, config), config, "ea8c2f4")
    boxes = box_documents(documents)
    def date_search(request, k):
        day, _, docs = day_candidates(boxes, request)
        return [SearchHit(doc.doc_id, 0) for doc in docs[:k]] if day is not None else []
    run_model(dataset, "date", Search(date_search), {"fallback": "empty"}, "20a8307 / report control")
    lexical = bm25.create_engine(documents, improved)
    run_model(dataset, "proximity", proximity_engine(documents, lexical),
              {"window": 8, "bonus": 0.08, "depth": 100}, "20261121T123737Z-2e0e615f")
    run_model(dataset, "prototype", Prototype(documents).mode("bm25"), {"k1": 1.2, "b": 0.75}, HISTORICAL_E5)
    controls = (
        ("routing", "routed", event_aware.create_engine, {"prospective_penalty": 0.0}),
        ("event-aware-status", "status", event_aware.create_engine, read_json("configs/search/bm25-event-aware.json")),
        ("routing-minilm-blend", "minilm", minilm_engine, read_json("configs/search/bm25-minilm.json")),
    )
    for current, prior, factory, config in controls:
        actual = ORIGINAL / f"holdout-{prior}"
        output = WORK / current
        if output.exists():
            continue
        if not actual.is_dir():
            engine = factory(documents, config)
            run_model(dataset, current, engine, engine.config, "ea8c2f4")
            continue
        recorded = read_json(actual / "run.json")
        stats = read_json(actual / "metrics.json")
        assert recorded["dataset"]["fingerprint"] == FINGERPRINT and stats["failed_queries"] == 0
        import shutil
        shutil.copytree(actual, output)


def minilm_suite(dataset, documents, full=False):
    reranker = MiniLM(MODEL_HOME / "minilm/model.onnx", 4)
    boxes = box_documents(documents)
    if not full:
        config = read_json("configs/search/bm25-minilm.json") | {"minilm_weight": 1.0}
        engine = minilm_engine(documents, config)
        run_model(dataset, "routing-minilm-pure", engine, engine.config, "ea8c2f4")
        def dated_only(request, k):
            day, text, docs = day_candidates(boxes, request)
            if day is None:
                return []
            return full_minilm(reranker, docs, text, k)
        run_model(dataset, "minilm", Search(dated_only),
                  {"model": "mMARCO INT8 ARM64", "candidate_scope": "receipt day", "fallback": "empty"}, "20a8307")
        return

    def search(request, k):
        _, text, docs = day_candidates(boxes, request)
        return full_minilm(reranker, docs, text, k)
    run_model(dataset, "minilm-all", Search(search),
              {"model": "mMARCO INT8 ARM64", "candidate_scope": "receipt day or available mailbox"}, "20a8307, extended")


def full_minilm(model, documents, text, k):
    if not documents or not text:
        return []
    ordered = sorted(documents, key=lambda doc: len(doc.doc))
    scores = model.score(text, [doc.doc for doc in ordered])
    return sorted((SearchHit(doc.doc_id, score) for doc, score in zip(ordered, scores, strict=True)),
                  key=lambda hit: (-hit.score, hit.doc_id))[:k]


def fp32_assets(documents):
    from mail_search.search.hybrid_index import load_vectors, model_identity

    filename = FP32 / "model.onnx"
    return EncoderAdapter(), load_vectors(FP32_INDEX, documents, model_identity(filename))


def rank_fusion(predictions_a, predictions_b, weight_b=1.0):
    result = {}
    for key, first in predictions_a.items():
        scores = defaultdict(float)
        for ranking, weight in ((first, 1.0), (predictions_b[key], weight_b)):
            for rank, doc in enumerate(ranking, start=1):
                scores[doc] += weight / (60 + rank)
        result[key] = sorted(scores, key=lambda doc: (-scores[doc], doc))[:100]
    return result


def historical_e5_suite(dataset, documents):
    from lexical_bonus_engine import LexicalBonusEngine
    from passage_engine import PassageEngine

    encoder, matrix = fp32_assets(documents)
    prototype = Prototype(documents, encoder, matrix)
    description = {"encoder": encoder.key, "device": "CPU", "model_sha256": encoder.model.identity[:64]}
    dense = PassageEngine(prototype.engine, {"date_filter": True})
    pred = run_model(dataset, "e5", dense, description | {"date_filter": True}, HISTORICAL_E5)
    run_model(dataset, "e5-no-date", PassageEngine(prototype.engine, {"date_filter": False}),
              description | {"date_filter": False}, HISTORICAL_E5)
    run_model(dataset, "prototype-hybrid", prototype.mode("hybrid"), description | {"rrf": 60}, HISTORICAL_E5)
    improved = bm25.create_engine(documents, read_json("configs/search/bm25-improved.json"))
    bonus = {"max_lexical_bonus": 0.01, "depth": 100}
    run_model(dataset, "e5-bm25-bonus", LexicalBonusEngine(dense, improved, bonus),
              description | bonus, HISTORICAL_E5)
    lexical_pred = read_predictions(WORK / "improved/predictions.jsonl")
    for name, lexical_weight in (("rrf-equal", 1.0), ("rrf-weighted", 0.25)):
        score_predictions(dataset, name, rank_fusion(pred, lexical_pred, lexical_weight),
                          description | {"rrf": 60, "lexical_weight": lexical_weight}, HISTORICAL_E5)
    eligible_boxes = {query.synthetic_user for query in dataset.queries}
    passages = get_passages(encoder, documents, eligible_boxes)
    engine = PassageEngine(prototype.engine, {"date_filter": True}, passages)
    run_model(dataset, "e5-passages", engine, description | {"date_filter": True, "passages": len(passages[0])}, HISTORICAL_E5)


def get_passages(encoder, docs, boxes):
    from passage_engine import START, STRIDE, WINDOW
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(str(FP32 / "tokenizer.json"))
    fragments = []
    for index, doc in enumerate(docs):
        if doc.synthetic_user not in boxes:
            continue
        offsets = tokenizer.encode(doc.doc, add_special_tokens=False).offsets
        if len(offsets) <= 508:
            continue
        for offset in range(START, len(offsets), STRIDE):
            end = min(offset + WINDOW, len(offsets)) - 1
            text = doc.doc[offsets[offset][0]:offsets[end][1]]
            if text.strip():
                fragments.append((index, text))
    fragments.sort(key=lambda x: len(x[1]))
    print("E5 tail passages", len(fragments), flush=True)
    vectors = [encoder.encode([text for _, text in fragments[i:i + 12]])
               for i in range(0, len(fragments), 12)]
    matrix = np.concatenate(vectors) if vectors else np.zeros((0, 384), dtype=np.float32)
    return np.asarray([i for i, _ in fragments], dtype=np.intp), matrix


def hybrid_suite(dataset, documents):
    from mail_search.search.hybrid import create_engine

    config = {"embeddings": str(FP32_INDEX), "e5_model": str(FP32 / "model.onnx"),
              "minilm_model": str(MODEL_HOME / "hybrid/minilm/model_qint8_arm64.onnx"),
              "date_filter": True, "retrieval_depth": 50, "rerank_depth": 30, "inference_threads": 4}
    for name, chosen in (("bm25-e5-rrf", config | {"minilm_model": None}), ("bm25-e5-minilm", config)):
        engine = create_engine(documents, chosen)
        run_model(dataset, name, engine, engine.config, HYBRID)


def native_e5(dataset):
    engine = e5.dataset_engine(dataset, MODEL_HOME / "e5", Path("artifacts/indexes/e5"))
    run_model(dataset, "e5-dev", engine, {
        "config": read_json("configs/search/e5-cosine.json"),
        "identity": engine.model.identity,
        "date_mode": "availability_only",
    }, "ea8c2f4")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("section", choices=("lexical", "minilm", "minilm-full", "e5-old", "hybrid", "e5-dev"))
    args = parser.parse_args()
    dataset = load_dataset(DATASET)
    assert dataset.summary["fingerprint"] == FINGERPRINT
    documents = tuple(sorted(dataset.documents.values(), key=lambda doc: doc.doc_id))
    handlers = {
        "lexical": lambda: lexical_suite(dataset, documents),
        "minilm": lambda: minilm_suite(dataset, documents),
        "minilm-full": lambda: minilm_suite(dataset, documents, full=True),
        "e5-old": lambda: historical_e5_suite(dataset, documents),
        "hybrid": lambda: hybrid_suite(dataset, documents),
        "e5-dev": lambda: native_e5(dataset),
    }
    handlers[args.section]()


if __name__ == "__main__":
    main()
