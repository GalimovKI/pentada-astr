import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date
import hashlib
import json
from pathlib import Path

import numpy as np
from mailsearch.encoder import Encoder
from mailsearch.metadata import receipt_date
from mail_search.domain.models import Document, Query
from mail_search.evaluation.runner import evaluate
from mail_search.ingestion.dataset import Dataset, load_dataset

from diagnostic import contrast_set
from encode import encode_sorted
from roles import EMAIL, NAME, RoleModel, headers, rule_role, spans

MODES = ("e5", "hard_day", "rule_soft", "llm_date", "llm_people", "llm_both")
DATE_BONUS, PERSON_BONUS = 0.16, 0.12


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def silver_queries(public, envelope):
    """Narrow official relevance to one observed exact address; diagnostic labels only."""
    queries, rels = [], {}
    for q in public.queries:
        groups = defaultdict(dict)
        for did, score in public.qrels[q.query_id].items():
            match = EMAIL.fullmatch(envelope[did]["sender"])
            if match and score > 0:
                groups[match[0].casefold()][did] = 1
        if not groups:
            continue
        addr = min(groups, key=lambda a: (-len(groups[a]), a))
        qid = "addr-" + q.query_id
        text = q.query.rstrip(".") + f", от {addr}."
        queries.append(Query(qid, q.synthetic_user, text, q.query_date))
        rels[qid] = groups[addr]
    return Dataset(public.documents, tuple(queries), rels, {"kind": "silver sender extension"})


def fixture():
    rows, requests, qrels, intents = contrast_set()
    docs = {d["doc_id"]: Document(**(d | {"doc_dt": date.fromisoformat(d["doc_dt"])})) for d in rows}
    queries = tuple(Query(**(q | {"query_date": date.fromisoformat(q["query_date"])})) for q in requests)
    return Dataset(docs, queries, qrels, {"kind": "controlled mailbox"}), intents


def score_set(dataset, encoder, roles, vectors, root):
    root.mkdir()
    dids = sorted(dataset.documents)
    docs = [dataset.documents[did] for did in dids]
    env = [headers(d.doc) for d in docs]
    addresses = defaultdict(set)
    for doc, pair in zip(docs, env, strict=True):
        for value in pair.values():
            if not EMAIL.search(value):
                addresses[doc.synthetic_user].update(n.casefold() for n in NAME.findall(value))
    people_lookup = defaultdict(list)
    for index, pair in enumerate(env):
        for role, value in pair.items():
            for token in EMAIL.findall(value) + NAME.findall(value):
                people_lookup[role, token.casefold()].append(index)
    boxes = np.array([d.synthetic_user for d in docs])
    days = np.array([d.doc_dt.toordinal() if d.doc_dt else -1 for d in docs])
    texts, hard_days, mentions, pairs = [], [], [], []
    for query in dataset.queries:
        hard_day, content = receipt_date(query.query, query.query_date)
        texts.append(" ".join(w for w in content.split() if w.lower() not in {"найди","покажи"}) or content)
        hard_days.append(date.fromisoformat(hard_day).toordinal() if hard_day else None)
        matches = spans(query.query, query.query_date, addresses[query.synthetic_user])
        mentions.append(matches)
        pairs.extend((query.query, m) for m in matches)
    decoded = iter(roles.classify(pairs))
    audits, predictions = {}, {mode: {} for mode in MODES}
    queries = encode_sorted(encoder, texts, query=True)
    for query, embedding, hard_day, matches in zip(dataset.queries, queries, hard_days, mentions, strict=True):
        scores = vectors @ embedding
        eligible = (boxes == query.synthetic_user) & (days <= query.query_date.toordinal())
        boosts = {key: np.zeros(len(docs)) for key in ("rule", "date", "person")}
        audits[query.query_id] = []
        for m in matches:
            role, confidence = next(decoded)
            rule = rule_role(query.query, m)
            audits[query.query_id].append(asdict(m) | dict(role=role, confidence=confidence, rule=rule))
            for target, label, weight in (("rule", rule, 1.0), (m.kind, role, confidence)):
                if label == "receipt":
                    delta = np.abs(days - date.fromisoformat(m.value).toordinal())
                    boosts[target] += weight * DATE_BONUS * np.exp(-delta / 1.5)
                elif label in ("sender", "recipient"):
                    indices = people_lookup[label, m.value]
                    boosts[target][indices] += weight * PERSON_BONUS
        for mode in MODES:
            mask, adjusted = eligible, scores
            if mode == "hard_day" and hard_day is not None:
                mask = eligible & (days == hard_day)
            elif mode == "rule_soft":
                adjusted = scores + boosts["rule"]
            elif mode == "llm_both":
                adjusted = scores + boosts["date"] + boosts["person"]
            elif mode in ("llm_date", "llm_people"):
                adjusted = scores + boosts["date" if mode == "llm_date" else "person"]
            ids = np.flatnonzero(mask)
            order = ids[np.argsort(-adjusted[ids], kind="stable")[:100]]
            predictions[mode][query.query_id] = [dids[i] for i in order]
    write(root/"extraction.json", audits)
    for mode, rankings in predictions.items():
        metrics, per_query = evaluate(dataset, rankings, [1, 5, 10, 20, 50, 100])
        out = root/mode
        out.mkdir()
        write(out/"metrics.json", metrics)
        with (out/"predictions.jsonl").open("w") as stream:
            for qid, ranking in rankings.items():
                stream.write(json.dumps(dict(query_id=qid, doc_ids=ranking)) + "\n")
        with (out/"per_query.jsonl").open("w") as stream:
            for row in per_query:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    return audits


def main():
    p = argparse.ArgumentParser()
    for key in ("archive","index","model","output"):
        p.add_argument(key, type=Path)
    args = p.parse_args()
    public = load_dataset(args.archive)
    control, gold = fixture()
    enc = Encoder("e5", "cuda")
    with np.load(args.index) as index:
        if (str(index["archive_sha"]) != hashlib.sha256(args.archive.read_bytes()).hexdigest()
            or str(index["encoder"]) != enc.key or list(index["ids"]) != sorted(public.documents)):
            raise ValueError("Index provenance mismatch")
        vectors = index["vectors"]
    model = RoleModel(args.model)
    args.output.mkdir(exist_ok=False)
    score_set(public, enc, model, vectors, args.output/"public")
    silver = silver_queries(public, {did: headers(d.doc) for did,d in public.documents.items()})
    score_set(silver, enc, model, vectors, args.output/"silver")
    control_vectors = encode_sorted(enc, [control.documents[did].doc for did in sorted(control.documents)])
    audits = score_set(control, enc, model, control_vectors, args.output/"controlled")
    for model_key in ("role","rule"):
        counts = Counter()
        for qid, fields in gold.items():
            wanted = {(k, v.casefold()) for k,v in fields.items() if k in ("receipt","sender","recipient")}
            got = {(a[model_key], a["value"]) for a in audits[qid] if a[model_key] in ("receipt","sender","recipient")}
            counts.update(exact=int(got == wanted), tp=len(got & wanted), fp=len(got-wanted), fn=len(wanted-got))
        write(args.output/f"controlled-parse-{model_key}.json", dict(counts, queries=len(gold)))


if __name__ == "__main__":
    main()
