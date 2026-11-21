"""Reproduce the archived model variants with the shared holdout scoring."""

import argparse
from contextlib import closing
from functools import lru_cache
import importlib.util
from pathlib import Path
import re
import sqlite3

from eval_suite import (
    DATASET, FP32, FINGERPRINT, HISTORICAL_E5, MODEL_HOME, SOFT, SOURCES, WORK,
    MiniLM, Prototype, Search, SearchHit, fp32_assets,
    load_dataset, rank_fusion, read_predictions, run_model, score_predictions,
)
import numpy as np

ENRON = "9d714d32f5adda7ebec5a1b8b60b2827000b53c3"


def indexed_batch(docs, positions, matrices, encoder, text):
    matrix = np.zeros((len(docs), encoder.dimensions), dtype=np.float32)
    if matrices is not None:
        matrix[:] = matrices
    ordered = sorted(positions, key=lambda i: len(text(docs[i])))
    for start in range(0, len(ordered), 32):
        indices = ordered[start:start + 32]
        matrix[indices] = encoder.encode([text(docs[i]) for i in indices])
    return matrix


def holdout_positions(dataset, docs):
    boxes = {q.synthetic_user for q in dataset.queries}
    return [i for i, doc in enumerate(docs) if doc.synthetic_user in boxes]


def run_rubert(dataset, docs):
    import torch
    from mailsearch.encoder import Encoder

    encoder = Encoder("rubert", "auto", local_only=True)
    positions = holdout_positions(dataset, docs)
    matrix = indexed_batch(docs, positions, None, encoder, lambda doc: doc.doc)
    ranks = run_model(dataset, "rubert", Prototype(docs, encoder, matrix).mode("semantic"), {
        "encoder": encoder.key, "device": encoder.device, "indexed_documents": len(positions),
        "torch": torch.__version__,
    }, HISTORICAL_E5)
    improved = read_predictions(WORK / "improved/predictions.jsonl")
    score_predictions(dataset, "rrf-rubert-bm25", rank_fusion(ranks, improved), {
        "encoder": encoder.key, "rrf": 60, "lexical": "improved", "depth": 100,
    }, ENRON)


def run_roles(dataset, docs, *, use_llm=True):
    import torch
    from huggingface_hub import snapshot_download
    from roles import RoleModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    spec = importlib.util.spec_from_file_location("archived_soft_eval", SOURCES / "soft/run.py")
    archived = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(archived)
    encoder, matrix = fp32_assets(docs)

    class Placeholder:
        def classify(self, pairs):
            return [("other", 0.0)] * len(pairs)

    class AppleRoles(RoleModel):
        def __init__(self, path):
            self.tokenizer = AutoTokenizer.from_pretrained(path, padding_side="left")
            torch.set_num_threads(4)
            device = "mps" if torch.backends.mps.is_available() else "cpu"
            dtype = torch.float16 if device == "mps" else torch.float32
            self.model = AutoModelForCausalLM.from_pretrained(path, dtype=dtype).to(device).eval()
            self.letters = [self.tokenizer.encode(letter, add_special_tokens=False)[0] for letter in "ABC"]
            if any(len(self.tokenizer.encode(c, add_special_tokens=False)) != 1 for c in "ABC"):
                raise ValueError("Expected single-token labels")

    snapshot = None
    runner = Placeholder()
    if use_llm:
        snapshot = Path(snapshot_download("Qwen/Qwen2.5-0.5B-Instruct", local_files_only=True))
        runner = AppleRoles(snapshot)
    output = WORK / ("soft-archive-llm" if use_llm else "soft-archive-rules")
    if not output.exists():
        archived.score_set(dataset, encoder, runner, matrix, output)
    names = {
        "e5": "meta-control", "hard_day": "meta-hard", "rule_date": "soft-date",
        "rule_people": "soft-people", "rule_soft": "soft-both", "llm_both": "qwen-meta",
        "llm_date": "soft-llm-date", "llm_people": "soft-llm-people",
    }
    for mode, name in names.items():
        is_llm = mode.startswith("llm_")
        if is_llm and not use_llm:
            continue
        predictions = read_predictions(output / mode / "predictions.jsonl")
        config = {"mode": mode, "encoder": encoder.key, "date_bonus": archived.DATE_BONUS,
                  "participant_bonus": archived.PERSON_BONUS}
        if is_llm:
            config.update(model="Qwen/Qwen2.5-0.5B-Instruct", revision=snapshot.name,
                          device=str(runner.model.device))
        score_predictions(dataset, name, predictions, config, SOFT)


def sqlite_index(dataset, docs, encoder, matrix):
    from mailsearch.store import SCHEMA

    path = WORK / "qwen-index.sqlite"
    with closing(sqlite3.connect(path)) as db:
        db.executescript(SCHEMA)
        identity = {"corpus": dataset.summary["sha256"]["documents.jsonl"], "encoder": encoder.key,
                    "count": str(len(docs))}
        existing = dict(db.execute("SELECT key, value FROM index_info"))
        if existing:
            if existing != identity:
                raise ValueError("Existing index identity differs")
        else:
            with db:
                db.executemany("INSERT INTO index_info VALUES (?, ?)", identity.items())
                db.executemany("INSERT INTO mail VALUES (?, ?, ?, ?, ?, ?, ?)", (
                    (doc.doc_id, doc.synthetic_user, doc.doc_dt.isoformat() if doc.doc_dt else None,
                     doc.doc, None, "[]", matrix[i].tobytes())
                    for i, doc in enumerate(docs)
                ))
    return path


def run_doc2query(dataset, docs):
    from mailsearch.query_expansion import CONFIGURATION, build_expansions
    from mailsearch.search import SearchEngine
    from mailsearch.store import open_index
    from passage_engine import PassageEngine

    encoder, vectors = fp32_assets(docs)
    path = sqlite_index(dataset, docs, encoder, vectors)
    with closing(open_index(path)) as db:
        index = SearchEngine(db, encoder, lexical=False)
        candidate_rows = index.benchmark_indices(
            {"query": q.query, "query_date": q.query_date.isoformat(), "synthetic_user": q.synthetic_user}
            for q in dataset.queries
        )
        build_expansions(db, encoder, [index.rows[i] for i in candidate_rows], 128)
        index = SearchEngine(db, encoder, lexical=False, augmented=True)
        configs = {"encoder": encoder.key, "expansion": CONFIGURATION, "eligible_documents": len(candidate_rows)}
        augmented = db.execute("SELECT count(*) FROM query_expansions WHERE configuration=?",
                               (f"{CONFIGURATION}:{encoder.key}",)).fetchone()[0]
        if augmented != len(candidate_rows):
            raise ValueError(f"Packed {augmented} expansions for {len(candidate_rows)} candidates")
        index.vectors = index.augmented_vectors
        engine = PassageEngine(index, {"date_filter": True})
        predictions = run_model(dataset, "qwen-doc", engine, configs, HISTORICAL_E5)
        improved = read_predictions(WORK / "improved/predictions.jsonl")
        score_predictions(dataset, "rrf-e5-doc2query-bm25", rank_fusion(predictions, improved),
                          configs | {"rrf": 60, "lexical": "improved"}, ENRON)
        phrases = dict(db.execute("SELECT doc_id, phrases FROM query_expansions WHERE configuration=?",
                                  (f"{CONFIGURATION}:{encoder.key}",)))
        import json
        text_by_id = {did: "\n".join(json.loads(raw)) for did, raw in phrases.items()}
        index.vectors = indexed_batch(docs, candidate_rows, None, encoder, lambda d: text_by_id.get(d.doc_id, ""))
        run_model(dataset, "e5-qwen-only", PassageEngine(index, {"date_filter": True}),
                  configs | {"phrase_vectors": len(candidate_rows), "original_weight": 0}, ENRON)


def contextual_focus(doc):
    fields = re.split(r"(?im)^(?:те[мm]а|subject)\s*:\s*", doc.doc, maxsplit=1)
    if len(fields) == 2:
        subject, _, rest = fields[-1].partition("\n")
        return (subject + "\n" + rest[:500]).strip()
    return doc.doc[:500]


def rerank_with_second(dataset, name, fused, pure, second):
    from fuse_predictions import fuse

    preds = {}
    for qid, ranking in fused.items():
        pool = set(ranking[:20])
        order = [did for did in second[qid] if did in pool]
        preds[qid] = fuse(pure[qid][:20], order, lexical_weight=1, depth=20) + ranking[20:]
    return score_predictions(dataset, name, preds, {
        "candidates": "rrf-enron-e5-bm25", "depth": 20, "combiner": "RRF 1:1",
    }, ENRON)


def run_enron_variants(dataset, docs):
    from mail_search.search.bm25 import create_engine
    from eval_suite import read_json

    encoder, vectors = fp32_assets(docs)
    positions = holdout_positions(dataset, docs)
    boxes = {}
    for i in positions:
        boxes.setdefault(docs[i].synthetic_user, []).append(i)

    def dense_engine(matrix):
        def search(query, k):
            eligible = [i for i in boxes[query.synthetic_user]
                        if docs[i].doc_dt is None or docs[i].doc_dt <= query.query_date]
            vector = encoder.encode([query.query], query=True)[0]
            scores = matrix[eligible] @ vector
            order = np.argsort(-scores, kind="stable")[:k]
            return [SearchHit(docs[eligible[i]].doc_id, float(scores[i])) for i in order]
        return Search(search)

    core = {"encoder": encoder.key, "date_mode": "availability_only"}
    baseline = run_model(dataset, "e5-enron", dense_engine(vectors), core, ENRON)
    focus = indexed_batch(docs, positions, None, encoder, contextual_focus)
    run_model(dataset, "e5-focus", dense_engine((vectors + focus) / 2),
              core | {"weights": [0.5, 0.5], "focus": "subject and first 500 characters"}, ENRON)

    for name, config_id in (("bm25-raw-no-date", "bm25"), ("stemmed-no-date", "bm25-stemmed"),
                            ("improved-no-date", "bm25-improved")):
        config = read_json(f"configs/search/{config_id}.json") | {"date_filter": False}
        run_model(dataset, name, create_engine(docs, config), config, ENRON)
    improved = read_predictions(WORK / "improved-no-date/predictions.jsonl")
    fused = rank_fusion(baseline, improved)
    score_predictions(dataset, "rrf-enron-e5-bm25", fused,
                      {"rrf": 60, "dense": "e5-enron", "lexical": "improved-no-date"}, ENRON)
    passages = read_predictions(WORK / "e5-passages/predictions.jsonl")
    score_predictions(dataset, "rrf-e5-passages-bm25", rank_fusion(passages, improved),
                      {"rrf": 60, "dense": "e5-passages", "lexical": "improved-no-date"}, ENRON)
    run_rerankers(dataset, fused, baseline, improved)


def run_rerankers(dataset, fused, dense, lexical):
    reranker = MiniLM(MODEL_HOME / "minilm/model.onnx", 4)
    pure = {}
    for query in dataset.queries:
        qid = query.query_id
        ids = fused[qid]
        prefix = ids[:20]
        values = reranker.score(query.query, [dataset.documents[did].doc for did in prefix])
        order = sorted(range(len(prefix)), key=lambda i: -values[i])
        pure[qid] = [prefix[i] for i in order] + ids[20:]
    score_predictions(dataset, "minilm-top20", pure, {
        "candidates": "rrf-enron-e5-bm25", "depth": 20, "model": "mMARCO INT8 ARM64",
    }, ENRON)
    rerank_with_second(dataset, "minilm-e5-top20", fused, pure, dense)
    rerank_with_second(dataset, "minilm-bm25-top20", fused, pure, lexical)


def finish_doc_rerank(dataset, docs):
    rankings = [read_predictions(WORK / name / "predictions.jsonl")
                for name in ("rrf-enron-e5-bm25", "minilm-top20", "qwen-doc")]
    rerank_with_second(dataset, "minilm-doc2query-top20", *rankings)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("section", choices=("rubert", "roles", "rules", "doc2query", "enron", "doc-rerank"))
    args = parser.parse_args()
    data = load_dataset(DATASET)
    assert data.summary["fingerprint"] == FINGERPRINT
    documents = tuple(sorted(data.documents.values(), key=lambda doc: doc.doc_id))
    if args.section in ("roles", "rules"):
        run_roles(data, documents, use_llm=args.section == "roles")
    else:
        {"rubert": run_rubert, "doc2query": run_doc2query, "enron": run_enron_variants, "doc-rerank": finish_doc_rerank}[args.section](data, documents)


if __name__ == "__main__":
    main()
