"""Load the official ZIP or its extracted directory, verifying its manifest."""

import hashlib
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .models import Document, Query

FILES = ("README.md", "documents.jsonl", "queries_dev.jsonl", "qrels_dev.jsonl")


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Dataset:
    documents: dict[str, Document]
    queries: tuple[Query, ...]
    qrels: dict[str, dict[str, int]]
    summary: dict


def _text(row: dict, field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field}: expected a nonempty string")
    return value


def _date(value: object, field: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValidationError(f"{field}: expected YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{field}: invalid calendar date {value}") from exc


def _rows(raw: bytes, name: str) -> list[dict]:
    rows = []
    for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise ValidationError(f"{name}:{number}: invalid JSON") from exc
        if not isinstance(row, dict):
            raise ValidationError(f"{name}:{number}: expected a JSON object")
        rows.append(row)
    return rows


def load_dataset(path: str | Path) -> Dataset:
    path = Path(path)
    names = (*FILES, "manifest.json")
    if path.is_dir():
        content = {name: (path / name).read_bytes() for name in names}
    else:
        with zipfile.ZipFile(path) as archive:
            if any(archive.namelist().count(name) != 1 for name in names):
                raise ValidationError("ZIP must contain each required file exactly once at its root")
            content = {name: archive.read(name) for name in names}
    manifest = json.loads(content["manifest.json"])
    if not isinstance(manifest, dict) or not isinstance(manifest.get("sha256"), dict):
        raise ValidationError("manifest.json: missing sha256 mapping")
    hashes = {name: hashlib.sha256(content[name]).hexdigest() for name in FILES}
    for name, actual in hashes.items():
        if actual != manifest["sha256"].get(name):
            raise ValidationError(f"SHA-256 mismatch: {name}")
    records = {name: _rows(content[name], name) for name in FILES if name.endswith(".jsonl")}
    for name, key in (("documents.jsonl", "documents"), ("queries_dev.jsonl", "queries"),
                      ("qrels_dev.jsonl", "qrels")):
        if type(manifest.get(key)) is not int or len(records[name]) != manifest[key]:
            raise ValidationError(f"manifest row count mismatch: {name}")

    documents = {}
    for number, row in enumerate(records["documents.jsonl"], 1):
        try:
            if "doc_dt" not in row:
                raise ValidationError("missing doc_dt")
            document = Document(_text(row, "doc_id"), _text(row, "synthetic_user"),
                                _text(row, "doc"),
                                None if row["doc_dt"] is None else _date(row["doc_dt"], "doc_dt"))
            if document.doc_id in documents:
                raise ValidationError(f"duplicate doc_id: {document.doc_id}")
            documents[document.doc_id] = document
        except ValidationError as exc:
            raise ValidationError(f"documents.jsonl:{number}: {exc}") from exc
    if not documents:
        raise ValidationError("empty document corpus")

    users = {d.synthetic_user for d in documents.values()}
    queries = {}
    for number, row in enumerate(records["queries_dev.jsonl"], 1):
        try:
            query = Query(_text(row, "query_id"), _text(row, "synthetic_user"),
                          _text(row, "query"), _date(row.get("query_date"), "query_date"))
            if query.query_id in queries:
                raise ValidationError(f"duplicate query_id: {query.query_id}")
            if query.synthetic_user not in users:
                raise ValidationError(f"unknown mailbox: {query.synthetic_user}")
            queries[query.query_id] = query
        except ValidationError as exc:
            raise ValidationError(f"queries_dev.jsonl:{number}: {exc}") from exc
    if not queries:
        raise ValidationError("empty query set")

    qrels = {qid: {} for qid in queries}
    for number, row in enumerate(records["qrels_dev.jsonl"], 1):
        try:
            qid, did = _text(row, "query_id"), _text(row, "doc_id")
            relevance = row.get("relevance")
            if type(relevance) is not int or relevance not in (0, 1):
                raise ValidationError("only binary relevance 0/1 is supported")
            if qid not in queries or did not in documents:
                raise ValidationError("unknown query_id or doc_id in qrels")
            if did in qrels[qid]:
                raise ValidationError(f"duplicate qrel: {qid}, {did}")
            query, document = queries[qid], documents[did]
            if relevance and document.synthetic_user != query.synthetic_user:
                raise ValidationError("relevant document belongs to another mailbox")
            if relevance and document.doc_dt and document.doc_dt > query.query_date:
                raise ValidationError("relevant document is unavailable on query_date")
            qrels[qid][did] = relevance
        except ValidationError as exc:
            raise ValidationError(f"qrels_dev.jsonl:{number}: {exc}") from exc

    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    summary = {
        "fingerprint": fingerprint, "sha256": hashes, "documents": len(documents),
        "queries": len(queries), "qrels": len(records["qrels_dev.jsonl"]),
        "mailboxes": len(users), "unknown_document_dates": sum(d.doc_dt is None for d in documents.values()),
        "single_relevant_queries": sum(sum(r.values()) == 1 for r in qrels.values()),
        "queries_without_relevant_documents": sum(not any(r.values()) for r in qrels.values()),
        "documents_by_mailbox": dict(sorted(Counter(d.synthetic_user for d in documents.values()).items())),
        "queries_by_mailbox": dict(sorted(Counter(q.synthetic_user for q in queries.values()).items())),
    }
    return Dataset(documents, tuple(queries.values()), qrels, summary)
