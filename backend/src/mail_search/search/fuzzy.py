"""Rank a dated slice of a mailbox with exact and partial word matches."""

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from heapq import nsmallest
from time import monotonic

from ..domain.models import Document, SearchHit, SearchRequest
from ..indexing.text import tokenize, tokenize_stemmed
from .bm25 import BM25Engine
from .dates import receipt_day
from .deadline import SEARCH_BUDGET_SECONDS, check_deadline


COMMAND = re.compile(r"^\s*(?:найди(?:те)?|найти|покажи(?:те)?|показать|поищи(?:те)?|поискать|ищу|нуж(?:ен|на|но|ны)|пожалуйста)\b\s*[, ]*")
MESSAGE_TYPE = re.compile(r"^(?:письм\w*|сообщени\w*|уведомлени\w*)\s+(?:о|об|обо|с|про|по)\s+")
SCRIPT_BOUNDARY = re.compile(r"(?<=[а-яё])(?=[a-z0-9])|(?<=[a-z0-9])(?=[а-яё])", re.I)
MAX_QUERY_CHARS = 4096


def query_terms(text: str) -> tuple[str, ...]:
    content = MESSAGE_TYPE.sub("", COMMAND.sub("", text))
    terms = tuple(dict.fromkeys(tokenize_stemmed(content)))
    content_terms = tuple(term for term in terms if len(term) > 2 or any(char.isdigit() for char in term))
    return content_terms or terms


def document_terms(text: str) -> Counter[str]:
    counts = Counter(tokenize_stemmed(SCRIPT_BOUNDARY.sub(" ", text)))
    # Split glued runs for word matching and retain complete alphanumeric IDs.
    counts.update(token for token in tokenize(text)
                  if any(char.isdigit() for char in token) and SCRIPT_BOUNDARY.search(token))
    return counts


@lru_cache(maxsize=65_536)
def character_grams(word: str, size: int) -> frozenset[str]:
    return frozenset(word[i:i + size] for i in range(len(word) - size + 1))


@lru_cache(maxsize=65_536)
def token_similarity(query: str, token: str) -> float:
    if query == token:
        return 1.0
    # Identifiers and numbers need exact matches.
    if min(len(query), len(token)) < 4 or not (query.isalpha() and token.isalpha()):
        return 0.0
    trigrams = character_grams(query, 3)
    shared_trigrams = len(trigrams & character_grams(token, 3))
    if not shared_trigrams:
        return 0.0
    bigrams = character_grams(query, 2)
    shared_bigrams = len(bigrams & character_grams(token, 2))
    prefix = 0
    for left, right in zip(query, token):
        if left != right:
            break
        prefix += 1
    return min(0.95, 0.28 * shared_bigrams / len(bigrams)
               + 0.26 * shared_trigrams / len(trigrams)
               + 0.46 * prefix / max(len(query), len(token)))


@dataclass
class DayIndex:
    doc_ids: list[str] = field(default_factory=list)
    postings: dict[str, list[tuple[str, int]]] = field(default_factory=lambda: defaultdict(list))


class FuzzyBM25Engine:
    def __init__(self, documents: tuple[Document, ...], *, k1: float = 1.2,
                 b: float = 0.75, fuzzy_weight: float = 1.4):
        if (isinstance(fuzzy_weight, bool) or not isinstance(fuzzy_weight, (int, float))
                or not math.isfinite(fuzzy_weight) or fuzzy_weight < 0):
            raise ValueError("fuzzy_weight must be a finite nonnegative number")
        self.config = {"k1": k1, "b": b, "fuzzy_weight": fuzzy_weight}
        self.bm25 = BM25Engine(documents, k1=k1, b=b, stemming=True, date_mode="contextual")
        self.by_day: dict[tuple[str, date], DayIndex] = defaultdict(DayIndex)
        vocabulary: dict[str, set[str]] = defaultdict(set)
        for document in documents:
            if document.doc_dt is not None:
                day = self.by_day[document.synthetic_user, document.doc_dt]
                day.doc_ids.append(document.doc_id)
                for term, frequency in document_terms(document.doc).items():
                    day.postings[term].append((document.doc_id, frequency))
                    if fuzzy_weight and len(term) >= 4 and term.isalpha():
                        vocabulary[document.synthetic_user].add(term)
        self.by_trigram: dict[str, dict[str, set[str]]] = {}
        for mailbox, terms in vocabulary.items():
            trigrams: dict[str, set[str]] = defaultdict(set)
            for term in terms:
                for gram in character_grams(term, 3):
                    trigrams[gram].add(term)
            self.by_trigram[mailbox] = trigrams

    def search(self, request: SearchRequest, k: int, *, deadline: float | None = None) -> list[SearchHit]:
        engine_deadline = monotonic() + SEARCH_BUDGET_SECONDS
        deadline = engine_deadline if deadline is None else min(deadline, engine_deadline)
        check_deadline(deadline)
        if len(request.query) > MAX_QUERY_CHARS:
            raise ValueError(f"query exceeds {MAX_QUERY_CHARS} characters")
        if not request.query.strip() or k < 1:
            raise ValueError("nonempty query and positive K required")
        if request.synthetic_user not in self.bm25.boxes:
            raise ValueError(f"unknown mailbox: {request.synthetic_user}")
        day, text = receipt_day(request.query, request.query_date)
        check_deadline(deadline)
        if day is None:
            return self.bm25.search(request, k, deadline=deadline)
        if day > request.query_date:
            return []
        documents = self.by_day.get((request.synthetic_user, day))
        if documents is None:
            return []
        terms = query_terms(text)
        if not terms:
            hits = [SearchHit(doc_id, 0.0) for doc_id in nsmallest(k, documents.doc_ids)]
            check_deadline(deadline)
            return hits

        index = self.bm25.boxes[request.synthetic_user]
        trigrams = self.by_trigram.get(request.synthetic_user, {})
        exact_scores: dict[str, float] = defaultdict(float)
        partial_scores: dict[str, float] = defaultdict(float)
        fuzzy_weight = self.config["fuzzy_weight"]
        k1 = self.config["k1"]
        for term in terms:
            check_deadline(deadline)
            matching_documents = len(index.postings.get(term, ()))
            weight = math.log1p((len(index.lengths) - matching_documents + 0.5)
                                / (matching_documents + 0.5))
            best: dict[str, float] = {}
            for doc_id, frequency in documents.postings.get(term, ()):
                check_deadline(deadline)
                exact_scores[doc_id] += weight * (frequency / (frequency + k1))
                best[doc_id] = 1.0

            # A nonzero partial match requires a shared trigram.
            if fuzzy_weight and len(term) >= 4 and term.isalpha():
                candidates: set[str] = set()
                for gram in character_grams(term, 3):
                    check_deadline(deadline)
                    candidates.update(trigrams.get(gram, ()))
                for token in candidates:
                    check_deadline(deadline)
                    matches = documents.postings.get(token)
                    if token != term and matches:
                        similarity = token_similarity(term, token)
                        for doc_id, _ in matches:
                            check_deadline(deadline)
                            if similarity > best.get(doc_id, 0):
                                best[doc_id] = similarity
            for doc_id, similarity in best.items():
                check_deadline(deadline)
                partial_scores[doc_id] += weight * similarity

        if not partial_scores:
            return []
        scores = ((doc_id, exact_scores.get(doc_id, 0.0) + fuzzy_weight * partial_scores[doc_id])
                  for doc_id in partial_scores)
        ranked = nsmallest(k, scores, key=lambda item: (-item[1], item[0]))
        if len(ranked) < k:
            remaining = (doc_id for doc_id in documents.doc_ids if doc_id not in partial_scores)
            ranked.extend((doc_id, 0.0) for doc_id in nsmallest(k - len(ranked), remaining))
        hits = [SearchHit(doc_id, score) for doc_id, score in ranked]
        check_deadline(deadline)
        return hits


def create_engine(documents: tuple[Document, ...], config: dict) -> FuzzyBM25Engine:
    unknown = set(config) - {"k1", "b", "fuzzy_weight"}
    if unknown:
        raise ValueError(f"unknown fuzzy BM25 options: {sorted(unknown)}")
    return FuzzyBM25Engine(documents, **config)
