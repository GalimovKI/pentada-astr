"""Fit dev-mail cutoffs on labelled mailboxes and evaluate on disjoint mailboxes."""
import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean

from mail_search.core import engine as loaders
from mail_search.core.presets import MODELS, model_settings
from mail_search.core.settings import Settings
from mail_search.ingestion.dataset import load_dataset


def stable_key(value):
    return sha256(value.encode()).digest()


def collect(settings, model, sample_per_box):
    ds = load_dataset(settings.search_dataset)
    loader = getattr(loaders, MODELS[model][1].split(":")[1])
    engine = loader(model_settings(settings, model)).engine
    boxes = defaultdict(list)
    for query in ds.queries:
        boxes[query.synthetic_user].append(query)
    holdout = set(sorted(boxes, key=stable_key)[::3])
    rows = []
    for box, queries in boxes.items():
        for query in sorted(queries, key=lambda q: stable_key(q.query_id))[:sample_per_box]:
            gold = {k for k, v in ds.qrels[query.query_id].items() if v}
            hits = engine.relevance_scores(query.request())
            rows.append((box in holdout, len(gold), [(hit.score, hit.doc_id in gold) for hit in hits]))
    return rows


def f1(row, threshold):
    _, positives, hits = row
    kept = hits[:10] if threshold is None else [h for h in hits if h[0] >= threshold]
    tp = sum(relevant for _, relevant in kept)
    return 2 * tp / (len(kept) + positives) if positives or kept else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--enron", type=Path, required=True)
    parser.add_argument("--e5-dir", type=Path, required=True)
    parser.add_argument("--minilm-dir", type=Path, required=True)
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--model", choices=MODELS, required=True)
    args = parser.parse_args()
    settings = Settings(database_url="postgresql://unused", minilm_model_dir=args.minilm_dir,
                        e5_model_dir=args.e5_dir, e5_index_dir=args.index_dir)
    corpora = {}
    for path, label, cap in ((args.official, "mail-public", None), (args.enron, "enronqa-en", 10)):
        corpora[label] = collect(settings.model_copy(update={"search_dataset": path}), args.model, cap)
    def metrics(threshold, holdout):
        return {label: mean(f1(row, threshold) for row in rows if row[0] == holdout)
                for label, rows in corpora.items()}
    grid = ([i / 200 for i in range(150, 195)] if args.model == "e5-cosine" else
            [i / 100 for i in range(5, 101)])
    threshold = max(grid, key=lambda t: (mean(metrics(t, False).values()), t))
    print(json.dumps(dict(model=args.model, threshold=threshold, train=metrics(threshold, False),
                          test=metrics(threshold, True), top10_test=metrics(None, True),
                          counts={k: [sum(not row[0] for row in rows), sum(row[0] for row in rows)]
                                  for k, rows in corpora.items()})))


if __name__ == "__main__":
    main()
