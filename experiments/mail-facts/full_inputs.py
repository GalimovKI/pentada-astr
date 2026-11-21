"""Prepare letters and queries without passing relevance labels to the extractor."""
import argparse
from dataclasses import asdict
from pathlib import Path
import json

from mail_search.ingestion.dataset import load_dataset
from run import fixture, silver_queries, headers


def datasets(archive):
    public = load_dataset(archive)
    silver = silver_queries(public, {did: headers(d.doc) for did, d in public.documents.items()})
    control, _ = fixture()
    return {"public": public, "silver": silver, "controlled": control}


def rows(archive):
    groups = datasets(archive)
    for group in ("public", "controlled"):
        for doc in groups[group].documents.values():
            yield dict(id=doc.doc_id, kind="letter", doc_dt=doc.doc_dt and doc.doc_dt.isoformat(), text=doc.doc)
    for ds in groups.values():
        for q in ds.queries:
            yield dict(id=q.query_id, kind="query", query_date=q.query_date.isoformat(), text=q.query)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("archive", type=Path)
    p.add_argument("out", type=Path)
    args = p.parse_args()
    with args.out.open("x") as f:
        for row in rows(args.archive):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
