"""A lexical BM25 baseline with mailbox and query-date constraints."""

import math
from collections import defaultdict
from heapq import nsmallest

from ..domain.models import Document, SearchHit, SearchRequest
from ..indexing.bm25 import build_bm25_index
from ..indexing.text import tokenize, tokenize_stemmed
from .dates import receipt_day, target_day


class BM25Engine:
    def __init__(self, documents: tuple[Document, ...], *, k1: float = 1.2,
                 b: float = 0.75, date_filter: bool = True,
                 stemming: bool = False, date_mode: str = "legacy"):
        if isinstance(k1, bool) or not isinstance(k1, (int, float)) or not math.isfinite(k1) or k1 <= 0:
            raise ValueError("k1 must be a finite positive number")
        if isinstance(b, bool) or not isinstance(b, (int, float)) or not math.isfinite(b) or not 0 <= b <= 1:
            raise ValueError("b must be in [0, 1]")
        if type(date_filter) is not bool:
            raise ValueError("date_filter must be a boolean")
        if type(stemming) is not bool:
            raise ValueError("stemming must be a boolean")
        if date_mode not in ("legacy", "contextual"):
            raise ValueError("date_mode must be legacy or contextual")
        self.config = {"k1": k1, "b": b, "date_filter": date_filter,
                       "stemming": stemming, "date_mode": date_mode}
        self.documents = {d.doc_id: d for d in documents}
        self.tokenize = tokenize_stemmed if stemming else tokenize
        self.boxes = build_bm25_index(documents, self.tokenize)

    def search(self, request: SearchRequest, k: int) -> list[SearchHit]:
        if not request.query.strip() or k < 1:
            raise ValueError("nonempty query and positive K required")
        if request.synthetic_user not in self.boxes:
            raise ValueError(f"unknown mailbox: {request.synthetic_user}")
        date_parser = receipt_day if self.config["date_mode"] == "contextual" else target_day
        day, text = (date_parser(request.query, request.query_date) if self.config["date_filter"]
                     else (None, request.query))
        index = self.boxes[request.synthetic_user]
        if day is not None and day > request.query_date:
            return []
        terms = sorted(set(self.tokenize(text)))
        if not terms and day is not None and self.config["date_mode"] == "contextual":
            ids = (doc_id for doc_id in index.lengths if self.documents[doc_id].doc_dt == day)
            return [SearchHit(doc_id, 0.0) for doc_id in nsmallest(k, ids)]
        postings, lengths, average = index.postings, index.lengths, index.average_length
        scores = defaultdict(float)
        for term in terms:
            entries = postings.get(term, ())
            idf = math.log1p((len(lengths) - len(entries) + 0.5) / (len(entries) + 0.5))
            for doc_id, frequency in entries:
                document = self.documents[doc_id]
                if document.doc_dt is not None and document.doc_dt > request.query_date:
                    continue
                if day is not None and document.doc_dt != day:
                    continue
                norm = frequency + self.config["k1"] * (1 - self.config["b"] + self.config["b"] * lengths[doc_id] / average)
                scores[doc_id] += idf * frequency * (self.config["k1"] + 1) / norm
        return [SearchHit(doc_id, score) for doc_id, score in
                nsmallest(k, scores.items(), key=lambda item: (-item[1], item[0]))]


def create_engine(documents: tuple[Document, ...], config: dict) -> BM25Engine:
    unknown = set(config) - {"k1", "b", "date_filter", "stemming", "date_mode"}
    if unknown:
        raise ValueError(f"unknown BM25 options: {sorted(unknown)}")
    return BM25Engine(documents, **config)
