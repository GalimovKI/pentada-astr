"""Rank the full mailbox benchmark using validated Qwen facts and frozen E5 vectors."""
import argparse
from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
from pathlib import Path

import numpy as np
from mailsearch.encoder import Encoder
from mailsearch.metadata import receipt_date
from mail_search.evaluation.runner import evaluate
from mail_search.indexing.text import normalize, tokenize_stemmed

from encode import encode_sorted
from full_inputs import datasets
from run import DATE_BONUS, PERSON_BONUS
from roles import EMAIL


def load_facts(folder, expected):
    facts = {}
    for path in sorted(folder.glob("*.jsonl")):
        with path.open() as stream:
            for line in stream:
                row = json.loads(line)
                if row["id"] in facts:
                    raise ValueError(f"Duplicate extraction {row['id']}")
                facts[row["id"]] = row
    if set(facts) != expected:
        raise ValueError(f"Incomplete extraction: {len(expected - facts.keys())} missing, "
                         f"{len(facts.keys() - expected)} extra")
    return facts


def sender_tokens(row):
    field = row.get("sender")
    if not field:
        return frozenset()
    raw = normalize(field["text"])
    emails = frozenset(EMAIL.findall(raw))
    return emails | frozenset(tokenize_stemmed(EMAIL.sub(" ", raw)))


def tagged_days(row):
    return {(d["role"], date.fromisoformat(d["iso"]).toordinal()) for d in row.get("dates", ())
            if d["role"] in ("receipt", "event", "deadline") and d.get("iso")}


def describe(ids, facts):
    rows = [facts[i] for i in ids]
    return dict(rows=len(rows), errors=sum("error" in r for r in rows),
                finish_reasons=dict(Counter(r["finish_reason"] for r in rows)),
                senders=dict(Counter(r["sender_source"] for r in rows if r.get("sender"))),
                any_normalized_day=sum(bool(tagged_days(r)) for r in rows),
                dates_by_role=dict(Counter(role for r in rows for role, _ in tagged_days(r))),
                rejected_fields=sum(r.get("rejected", 0) for r in rows))


def date_bonus(query_days, received, mentions):
    bonus = np.zeros(len(received))
    for role, day in sorted(query_days):
        if role == "receipt":
            delta = np.abs(received - day)
            bonus += DATE_BONUS * np.exp(-delta / 1.5)
        else:
            by_doc = np.zeros(len(received))
            for candidate_day, ids in mentions[role].items():
                value = DATE_BONUS * np.exp(-abs(day - candidate_day) / 1.5)
                by_doc[ids] = np.maximum(by_doc[ids], value)
            bonus += by_doc
    return bonus


def rank(ds, facts, encoder, vectors):
    ids = sorted(ds.documents)
    docs = [ds.documents[i] for i in ids]
    boxes = np.array([d.synthetic_user for d in docs])
    received = np.array([d.doc_dt.toordinal() if d.doc_dt else -1 for d in docs])
    senders = [sender_tokens(facts[i]) for i in ids]
    mentions = {role: defaultdict(list) for role in ("event", "deadline")}
    for index, did in enumerate(ids):
        for role, day in tagged_days(facts[did]):
            if role in mentions:
                mentions[role][day].append(index)
    content = []
    for q in ds.queries:
        _, text = receipt_date(q.query, q.query_date)
        content.append(" ".join(w for w in text.split() if w.lower() not in {"найди","покажи"}) or text)
    queries = encode_sorted(encoder, content, query=True)
    predictions = {key: {} for key in ("e5", "date", "sender", "full")}
    for q, vector in zip(ds.queries, queries, strict=True):
        base = vectors @ vector
        eligible = np.flatnonzero((boxes == q.synthetic_user) & (received <= q.query_date.toordinal()))
        f = facts[q.query_id]
        temporal = date_bonus(tagged_days(f), received, mentions)
        name = sender_tokens(f)
        person = np.zeros(len(ids))
        if name:
            person[eligible] = [PERSON_BONUS if name <= senders[i] else 0 for i in eligible]
        for mode, scores in (("e5",base),("date",base + temporal),("sender",base + person),
                             ("full",base + temporal + person)):
            top = eligible[np.argsort(-scores[eligible], kind="stable")[:100]]
            predictions[mode][q.query_id] = [ids[i] for i in top]
    return predictions


def dump_rows(path, rows):
    with path.open("x") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("archive","index","facts","out"):
        p.add_argument(name, type=Path)
    args = p.parse_args()
    groups = datasets(args.archive)
    required = set()
    for ds in groups.values():
        required.update(ds.documents)
        required.update(q.query_id for q in ds.queries)
    facts = load_facts(args.facts, required)
    encoder = Encoder("e5", "cuda")
    with np.load(args.index) as idx:
        if (str(idx["archive_sha"]) != hashlib.sha256(args.archive.read_bytes()).hexdigest()
            or str(idx["encoder"]) != encoder.key or list(idx["ids"]) != sorted(groups["public"].documents)):
            raise ValueError("Index provenance mismatch")
        corpus_vectors = idx["vectors"]
    args.out.mkdir(exist_ok=False)
    coverage = {}
    for name, ds in groups.items():
        vectors = corpus_vectors
        if name == "controlled":
            vectors = encode_sorted(encoder, [ds.documents[i].doc for i in sorted(ds.documents)])
        coverage[name] = dict(documents=describe(ds.documents, facts),
                              queries=describe((q.query_id for q in ds.queries), facts))
        for mode, rankings in rank(ds, facts, encoder, vectors).items():
            dest = args.out/name/mode
            dest.mkdir(parents=True)
            metrics, per_query = evaluate(ds, rankings, [1,5,10,20,50,100])
            (dest/"metrics.json").write_text(json.dumps(metrics, indent=2)+"\n")
            dump_rows(dest/"predictions.jsonl", (dict(query_id=q, doc_ids=hits) for q,hits in rankings.items()))
            dump_rows(dest/"per_query.jsonl", per_query)
    (args.out/"coverage.json").write_text(json.dumps(coverage, indent=2)+"\n")


if __name__ == "__main__":
    main()
