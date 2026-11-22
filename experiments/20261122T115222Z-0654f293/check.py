"""Run from repository root with backend/.venv/bin/python check.py ARchive OUT MODE."""
import json
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock
import sys

from fastapi.testclient import TestClient
from mail_search.api.app import create_app
from mail_search.cli import DEFAULT_KS
from mail_search.core.provenance import code_version
from mail_search.core.settings import Settings
from mail_search.core.presets import MAIL_THRESHOLDS
from mail_search.domain.models import SearchHit, SearchRequest
from mail_search.evaluation.runner import run_engine, evaluate, write_run
from mail_search.ingestion.dataset import load_dataset
from mail_search.storage.repository import MessagePreview


class Store:
    def __init__(self, data):
        self.data = data
        self.boxes = sorted({doc.synthetic_user for doc in data.documents.values()})

    def import_fingerprint(self):
        return self.data.summary["fingerprint"]

    def list_mailboxes(self):
        return self.boxes

    def get_messages(self, user, ids, query_date):
        docs = [self.data.documents[doc_id] for doc_id in ids]
        assert all(doc.synthetic_user == user and (doc.doc_dt is None or doc.doc_dt <= query_date) for doc in docs)
        return docs

    def get_previews(self, user, ids, query_date):
        docs = self.get_messages(user, ids, query_date)
        return [MessagePreview(doc.doc_id, doc.synthetic_user, doc.doc_dt, doc.doc[:200]) for doc in docs]


class ThroughAPI:
    def __init__(self, client, combined):
        self.client = client
        self.flags = {"correct_typos": True, "expand_word_forms": True} if combined else {}

    def search(self, req, k, threshold=None):
        body = dict(query=req.query, query_date=req.query_date.isoformat(), limit=k, **self.flags)
        if threshold is not None:
            body["relevance_threshold"] = threshold
        response = self.client.post(f"/api/v1/mailboxes/{req.synthetic_user}/search", params={"model":"bm25-event-aware"}, json=body)
        response.raise_for_status()
        return [SearchHit(i["doc_id"],i["score"]) for i in response.json()["items"]]


def main():
    archive, dest, mode = sys.argv[1:]
    assert mode in ("baseline", "combined")
    dataset = load_dataset(archive)
    settings = Settings(database_url="postgresql://unused",search_dataset=archive)
    app = create_app(settings, database_factory=lambda _: Mock(), store_factory=lambda _: Store(dataset))
    with TestClient(app) as client:
        app.state.evaluations = Mock(models={"bm25-event-aware"})
        transport = ThroughAPI(client, mode == "combined")
        preds, _, errs = run_engine(dataset, transport, max(DEFAULT_KS))
        metrics, per_query = evaluate(dataset, preds, DEFAULT_KS, errors=errs)
        meta = dict(status="ok" if not errs else "failed", created_at=datetime.now(timezone.utc).isoformat(),
                    engine="bm25-event-aware", engine_config={"api_flags": transport.flags},
                    dataset=dataset.summary, code=code_version(), ks=DEFAULT_KS, fingerprint=dataset.summary["fingerprint"])
        dest = Path(dest)/mode
        write_run(dest, meta, metrics, per_query, preds)
        if errs: raise RuntimeError(next(iter(errs.values())))
        sample = SearchRequest("", "box-12259a301ee2", date(2030,1,1))
        diagnostics = {}
        for term in ("штраф","штрфа","штрафик","оштрафовали"):
            hits = transport.search(replace(sample,query=term),100,MAIL_THRESHOLDS["bm25-event-aware"])
            diag = {"count":len(hits), "with_literal_input":sum(term in dataset.documents[h.doc_id].doc.lower() for h in hits),
                    "with_substring_shtraf":sum("штраф" in dataset.documents[h.doc_id].doc.lower() for h in hits),
                    "doc_ids":[h.doc_id for h in hits]}
            diagnostics[term] = diag
        (dest/"diagnostics.json").write_text(json.dumps(diagnostics, ensure_ascii=False,indent=2)+"\n")
        print(mode,metrics["by_k"]["10"],metrics["failed_queries"], [(k,v["count"],v["with_substring_shtraf"]) for k,v in diagnostics.items()])


if __name__ == "__main__":
    main()
