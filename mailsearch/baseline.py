"""A lexical BM25 baseline with mailbox and query-date constraints."""

import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, timedelta
from heapq import nsmallest

from .models import Document, SearchHit, SearchRequest

MONTHS = {name: i for i, name in enumerate(("января", "февраля", "марта", "апреля", "мая",
          "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"), 1)}
RUSSIAN_DATE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})(?:\s+года)?\b")
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
RELATIVE = re.compile(r"\b(позавчера|вчера|сегодня)\b")


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")


def tokenize(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", normalize(text))


def target_day(text: str, anchor: date) -> tuple[date | None, str]:
    """Recognize a single day. Ambiguous/multiple dates are left to lexical search."""
    text = normalize(text)
    matches = []
    for match in RELATIVE.finditer(text):
        delta = {"сегодня": 0, "вчера": 1, "позавчера": 2}[match[1]]
        matches.append((anchor - timedelta(days=delta), match.span()))
    for match in RUSSIAN_DATE.finditer(text):
        matches.append((date(int(match[3]), MONTHS[match[2]], int(match[1])), match.span()))
    for match in ISO_DATE.finditer(text):
        matches.append((date.fromisoformat(match[0]), match.span()))
    if len(matches) != 1:
        return None, text
    day, (start, end) = matches[0]
    return day, text[:start] + " " + text[end:]


class BM25Engine:
    def __init__(self, documents: tuple[Document, ...], *, k1: float = 1.2,
                 b: float = 0.75, date_filter: bool = True):
        if isinstance(k1, bool) or not isinstance(k1, (int, float)) or not math.isfinite(k1) or k1 <= 0:
            raise ValueError("k1 must be a finite positive number")
        if isinstance(b, bool) or not isinstance(b, (int, float)) or not math.isfinite(b) or not 0 <= b <= 1:
            raise ValueError("b must be in [0, 1]")
        if type(date_filter) is not bool:
            raise ValueError("date_filter must be a boolean")
        self.config = {"k1": k1, "b": b, "date_filter": date_filter}
        self.documents = {d.doc_id: d for d in documents}
        self.boxes = {}
        grouped = defaultdict(list)
        for document in documents:
            grouped[document.synthetic_user].append(document)
        for user, items in grouped.items():
            postings = defaultdict(list)
            lengths = {}
            for document in items:
                tokens = tokenize(document.doc)
                lengths[document.doc_id] = len(tokens)
                for term, frequency in Counter(tokens).items():
                    postings[term].append((document.doc_id, frequency))
            self.boxes[user] = (postings, lengths, sum(lengths.values()) / len(items) or 1.0)

    def search(self, request: SearchRequest, k: int) -> list[SearchHit]:
        if not request.query.strip() or k < 1:
            raise ValueError("nonempty query and positive K required")
        if request.synthetic_user not in self.boxes:
            raise ValueError(f"unknown mailbox: {request.synthetic_user}")
        day, text = (target_day(request.query, request.query_date) if self.config["date_filter"]
                     else (None, request.query))
        postings, lengths, average = self.boxes[request.synthetic_user]
        scores = defaultdict(float)
        for term in sorted(set(tokenize(text))):
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
    unknown = set(config) - {"k1", "b", "date_filter"}
    if unknown:
        raise ValueError(f"unknown BM25 options: {sorted(unknown)}")
    return BM25Engine(documents, **config)
