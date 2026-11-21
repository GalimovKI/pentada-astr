import hashlib
import json
from pathlib import Path


def fixture(root: Path, *, documents=None, queries=None, qrels=None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    documents = documents if documents is not None else [
        {"doc_id": did, "synthetic_user": user, "doc": "Чек магазина. Оплата покупок.", "doc_dt": dt}
        for did, user, dt in (("d1", "a", "2025-01-01"), ("d2", "a", "2025-01-02"),
                              ("future", "a", "2025-01-03"), ("unknown-date", "a", None),
                              ("other-box", "b", "2025-01-01"))]
    queries = queries if queries is not None else [
        {"query_id": "q1", "synthetic_user": "a", "query": "чек вчера", "query_date": "2025-01-02"},
        {"query_id": "q2", "synthetic_user": "a", "query": "чек", "query_date": "2025-01-02"}]
    qrels = qrels if qrels is not None else [
        {"query_id": "q1", "doc_id": "d1", "relevance": 1},
        {"query_id": "q2", "doc_id": "d1", "relevance": 1},
        {"query_id": "q2", "doc_id": "d2", "relevance": 1}]
    (root / "README.md").write_text("Synthetic test fixture\n", encoding="utf-8")
    hashes = {"README.md": hashlib.sha256((root / "README.md").read_bytes()).hexdigest()}
    for name, rows in (("documents.jsonl", documents), ("queries_dev.jsonl", queries), ("qrels_dev.jsonl", qrels)):
        data = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode()
        (root / name).write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    (root / "manifest.json").write_text(json.dumps({
        "documents": len(documents), "queries": len(queries), "qrels": len(qrels), "sha256": hashes,
    }), encoding="utf-8")
    return root
