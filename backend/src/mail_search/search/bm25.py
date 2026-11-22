"""A lexical BM25 baseline with mailbox and query-date constraints."""

import math
import re
from collections import defaultdict
from collections.abc import Callable
from heapq import nsmallest

from ..domain.models import Document, SearchHit, SearchRequest
from ..indexing.bm25 import build_bm25_index, build_corpus_statistics
from ..indexing.text import normalize, tokenize, tokenize_stemmed
from .dates import receipt_day, target_day
from .deadline import check_deadline

LEADING_COMMAND = re.compile(r"^\s*(?:найди|найти|покажи|показать|поищи|поискать|отыщи|отыскать|выведи|вывести|найдите|покажите)\b[\s,:-]*")
MAIL_INTRO = re.compile(r"^\s*(?:письм[а-я]*|уведомлен[а-я]*|сообщени[а-я]*)\s+(?:о|об|про|с)\s+")


class BM25Engine:
    def __init__(self, documents: tuple[Document, ...], *, k1: float = 1.2,
                 b: float = 0.75, date_filter: bool = True,
                 stemming: bool = False, date_mode: str = "legacy",
                 statistics_scope: str = "mailbox", query_wrapper_weight: float = 1.0):
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
        if statistics_scope not in ("mailbox", "corpus"):
            raise ValueError("statistics_scope must be mailbox or corpus")
        if (type(query_wrapper_weight) not in (int, float) or not math.isfinite(query_wrapper_weight)
                or not 0 < query_wrapper_weight <= 1):
            raise ValueError("query_wrapper_weight must be in (0, 1]")
        self.config = {"k1": k1, "b": b, "date_filter": date_filter,
                       "stemming": stemming, "date_mode": date_mode,
                       "statistics_scope": statistics_scope, "query_wrapper_weight": query_wrapper_weight}
        self.documents = {d.doc_id: d for d in documents}
        self.tokenize = tokenize_stemmed if stemming else tokenize
        self.boxes = build_bm25_index(documents, self.tokenize)
        self.corpus_stats = build_corpus_statistics(self.boxes) if statistics_scope == "corpus" else None

    def _term_weights(self, text: str) -> dict[str, float]:
        terms = sorted(set(self.tokenize(text)))
        wrapper_weight = self.config["query_wrapper_weight"]
        if wrapper_weight == 1:
            return dict.fromkeys(terms, 1.0)
        content = LEADING_COMMAND.sub("", normalize(text), count=1)
        content = MAIL_INTRO.sub("", content, count=1)
        topical_terms = set(self.tokenize(content))
        return {term: 1.0 if not topical_terms or term in topical_terms else wrapper_weight for term in terms}

    def search(self, request: SearchRequest, k: int, *, deadline: float | None = None) -> list[SearchHit]:
        if deadline is not None:
            check_deadline(deadline)
        if not request.query.strip() or k < 1:
            raise ValueError("nonempty query and positive K required")
        if request.synthetic_user not in self.boxes:
            raise ValueError(f"unknown mailbox: {request.synthetic_user}")
        date_parser = receipt_day if self.config["date_mode"] == "contextual" else target_day
        day, text = (date_parser(request.query, request.query_date) if self.config["date_filter"]
                     else (None, request.query))
        if day is not None and day > request.query_date:
            return []

        def eligible(doc_id: str) -> bool:
            received = self.documents[doc_id].doc_dt
            return ((received is None or received <= request.query_date)
                    and (day is None or received == day))

        if day is not None and self.config["date_mode"] == "contextual" and not self.tokenize(text):
            ids = (doc_id for doc_id in self.boxes[request.synthetic_user].lengths if eligible(doc_id))
            hits = [SearchHit(doc_id, 0.0) for doc_id in nsmallest(k, ids)]
            if deadline is not None:
                check_deadline(deadline)
            return hits
        return self.rank(text, request.synthetic_user, k, eligible, deadline=deadline)

    def rank(self, text: str, mailbox: str, k: int, eligible: Callable[[str], bool],
             *, deadline: float | None = None) -> list[SearchHit]:
        index = self.boxes[mailbox]
        term_weights = self._term_weights(text)
        postings, lengths, average = index.postings, index.lengths, index.average_length
        document_count = len(lengths)
        if self.corpus_stats is not None:
            document_count = self.corpus_stats.document_count
            average = self.corpus_stats.average_length
        scores = defaultdict(float)
        for term, weight in term_weights.items():
            if deadline is not None:
                check_deadline(deadline)
            entries = postings.get(term, ())
            frequency_in_corpus = self.corpus_stats.document_frequency[term] if self.corpus_stats else len(entries)
            idf = math.log1p((document_count - frequency_in_corpus + 0.5) / (frequency_in_corpus + 0.5))
            for position, (doc_id, frequency) in enumerate(entries):
                if deadline is not None and position % 128 == 0:
                    check_deadline(deadline)
                if not eligible(doc_id):
                    continue
                norm = frequency + self.config["k1"] * (1 - self.config["b"] + self.config["b"] * lengths[doc_id] / average)
                scores[doc_id] += weight * idf * frequency * (self.config["k1"] + 1) / norm
        hits = [SearchHit(doc_id, score) for doc_id, score in
                nsmallest(k, scores.items(), key=lambda item: (-item[1], item[0]))]
        if deadline is not None:
            check_deadline(deadline)
        return hits


def create_engine(documents: tuple[Document, ...], config: dict) -> BM25Engine:
    unknown = set(config) - {"k1", "b", "date_filter", "stemming", "date_mode",
                             "statistics_scope", "query_wrapper_weight"}
    if unknown:
        raise ValueError(f"unknown BM25 options: {sorted(unknown)}")
    return BM25Engine(documents, **config)
