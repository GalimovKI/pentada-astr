"""Route lexical search by the presence of a receipt day."""

from ..domain.models import Document, SearchHit, SearchRequest
from .bm25 import BM25Engine
from .dates import receipt_day
from .fuzzy import FuzzyBM25Engine


class RoutedBM25Engine:
    def __init__(self, documents: tuple[Document, ...]):
        self.dated = FuzzyBM25Engine(documents, fuzzy_weight=1.4)
        self.undated = BM25Engine(documents, stemming=True, date_mode="contextual",
                                 statistics_scope="corpus", query_wrapper_weight=0.1)

    def search(self, request: SearchRequest, k: int) -> list[SearchHit]:
        day, _ = receipt_day(request.query, request.query_date)
        engine = self.dated if day is not None else self.undated
        return engine.search(request, k)
