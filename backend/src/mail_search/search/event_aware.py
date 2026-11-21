"""Optional lexical reranking within the selected receipt day."""

from collections import Counter
from dataclasses import dataclass
import math
import re

from ..domain.models import Document, SearchHit, SearchRequest
from ..indexing.text import tokenize_stemmed
from .dates import receipt_day
from .fuzzy import SCRIPT_BOUNDARY, query_terms, token_similarity
from .routed_bm25 import RoutedBM25Engine

SUBJECT = re.compile(r"^[ \t]*(?:тема|subject)[ \t]*:[ \t]*([^\r\n]+)", re.IGNORECASE | re.MULTILINE)
CLAUSE_BOUNDARY = re.compile(r"[.!?;,:\r\n]+")
MODAL_STEMS = frozenset(("разрешен", "разреш", "заявк", "запрос", "согласован"))


def prospective_only(text: str) -> frozenset[str]:
    """Find action heads mentioned solely after a permission or request marker."""
    heads: Counter[str] = Counter()
    tokens: Counter[str] = Counter()
    for clause in CLAUSE_BOUNDARY.split(text):
        stems = tokenize_stemmed(SCRIPT_BOUNDARY.sub(" ", clause))
        tokens.update(stems)
        for index, stem in enumerate(stems):
            if stem not in MODAL_STEMS:
                continue
            for link in range(index + 1, min(index + 4, len(stems) - 1)):
                if stems[link] == "на":
                    heads[stems[link + 1]] += 1
                    break
    ordinary = tokens - heads
    return frozenset(head for head in heads
                     if not any(token_similarity(head, stem) >= 0.65 for stem in ordinary))


@dataclass(frozen=True)
class Evidence:
    prospective: frozenset[str]
    subject: frozenset[str]


class EventAwareEngine:
    def __init__(self, documents: tuple[Document, ...], options: dict):
        self.config = options
        self.baseline = RoutedBM25Engine(documents)
        self.evidence = {}
        if options["prospective_penalty"] or options["subject_bonus"]:
            for document in documents:
                if document.doc_dt is None:
                    continue
                text = document.doc
                subject = SUBJECT.search(text) if options["subject_bonus"] else None
                subject_terms = frozenset(tokenize_stemmed(subject[1])) if subject else frozenset()
                prospective = prospective_only(text) if options["prospective_penalty"] else frozenset()
                if prospective or subject_terms:
                    self.evidence[document.doc_id] = Evidence(prospective, subject_terms)

    def search(self, request: SearchRequest, k: int) -> list[SearchHit]:
        if not self.evidence or k < 1:
            return self.baseline.search(request, k)
        day, content = receipt_day(request.query, request.query_date)
        terms = set(query_terms(content)) if day is not None else set()
        if not terms:
            return self.baseline.search(request, k)

        depth = self.config["rerank_depth"]
        hits = self.baseline.search(request, max(k, depth))
        prefix = hits[:depth]
        penalty = self.config["prospective_penalty"] if terms.isdisjoint(MODAL_STEMS) else 0
        bonus = self.config["subject_bonus"]

        def adjust(hit: SearchHit) -> float:
            evidence = self.evidence.get(hit.doc_id)
            if evidence is None:
                return hit.score
            score = hit.score
            if penalty and not terms.isdisjoint(evidence.prospective):
                score *= 1 - penalty
            if bonus and len(terms & evidence.subject) >= 2:
                score *= 1 + bonus
            return score

        scores = [adjust(hit) for hit in prefix]
        order = sorted(range(len(prefix)), key=lambda i: -scores[i])
        if order == list(range(len(prefix))):
            return hits[:k]
        reordered = [prefix[i] for i in order] + hits[depth:]
        return [SearchHit(hit.doc_id, 1 / rank) for rank, hit in enumerate(reordered[:k], 1)]


def create_engine(documents: tuple[Document, ...], config: dict) -> EventAwareEngine:
    defaults = {"rerank_depth": 20, "prospective_penalty": 0.55, "subject_bonus": 0.0}
    unknown = config.keys() - defaults.keys()
    if unknown:
        raise ValueError(f"Unknown event-aware options: {sorted(unknown)}")
    options = {**defaults, **config}
    if type(options["rerank_depth"]) is not int or options["rerank_depth"] < 1:
        raise ValueError("rerank_depth must be a positive integer")
    for name in ("prospective_penalty", "subject_bonus"):
        value = options[name]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{name} must be a number in [0, 1]")
    return EventAwareEngine(documents, options)
