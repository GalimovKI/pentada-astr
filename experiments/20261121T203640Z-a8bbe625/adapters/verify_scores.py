"""Independently score every saved ranking attached to the holdout tab."""

import json
from pathlib import Path
import re
import sys

from mail_search.evaluation.runner import evaluate, read_predictions
from mail_search.ingestion.dataset import load_dataset

report, dataset, runs = map(Path, sys.argv[1:])
source = load_dataset(dataset)
html = report.read_text(encoding="utf-8")
embedded = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
holdout = json.loads(embedded[1])["holdout"]
assert holdout["fingerprint"] == source.summary["fingerprint"]
assert len(holdout["queries"]) == len(source.queries)
for method in holdout["methods"]:
    path = runs / method["id"]
    expected = json.loads((path / "metrics.json").read_text())
    ks = sorted(map(int, expected["by_k"]))
    predictions = read_predictions(path / "predictions.jsonl")
    measured, details = evaluate(source, predictions, ks)
    assert measured == expected, method["id"]
    assert measured["by_k"] == method["scores"]["all"], method["id"]
    assert len(details) == 60
print(f"Recomputed all rank metrics for {len(holdout['methods'])} methods")
