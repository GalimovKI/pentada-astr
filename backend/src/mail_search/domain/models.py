from dataclasses import dataclass
from datetime import date
from typing import Protocol, Sequence


@dataclass(frozen=True)
class Document:
    doc_id: str
    synthetic_user: str
    doc: str
    doc_dt: date | None


@dataclass(frozen=True)
class SearchRequest:
    query: str
    synthetic_user: str
    query_date: date


@dataclass(frozen=True)
class Query:
    query_id: str
    synthetic_user: str
    query: str
    query_date: date

    def request(self) -> SearchRequest:
        return SearchRequest(self.query, self.synthetic_user, self.query_date)


@dataclass(frozen=True)
class SearchHit:
    doc_id: str
    score: float


class SearchEngine(Protocol):
    def search(self, request: SearchRequest, k: int) -> Sequence[SearchHit]: ...
