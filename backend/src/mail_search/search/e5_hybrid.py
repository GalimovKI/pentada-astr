"""Compose event-aware BM25 and multilingual E5 within the same mailbox and receipt day."""
from ..domain.models import SearchHit
from .dates import receipt_day
from .relevance import relative_scores


class E5HybridEngine:
    def __init__(self, lexical, dense, config):
        self.lexical = lexical
        self.dense = dense
        self.config = config
        self.depth = config["candidate_depth"]
        self.strategy = config["strategy"]
        if self.strategy not in {"rrf", "dense_first", "lexical_first"} or self.depth < 1:
            raise ValueError("Invalid hybrid search configuration")
        if self.strategy != "lexical_first" and not 0 <= config["lexical_weight"] <= 1:
            raise ValueError("lexical_weight must be in [0, 1]")
        if self.strategy == "rrf" and config["rrf_constant"] < 0:
            raise ValueError("rrf_constant must be non-negative")

    @property
    def model(self):
        return self.dense.model

    def search(self, request, k):
        if k < 1:
            raise ValueError("positive K required")
        return self.relevance_scores(request)[:k]

    def relevance_scores(self, request):
        day, _ = receipt_day(request.query, request.query_date)
        if self.strategy == "lexical_first":
            candidates = self.lexical.search(request, self.depth)
            hits, _ = self.dense.search_page(request, self.depth, receipt_date=day,
                                            candidate_ids=[h.doc_id for h in candidates])
            return [SearchHit(h.doc_id, max(0.0, min(1.0, h.score))) for h in hits]

        dense, _ = self.dense.search_page(request, self.depth, receipt_date=day)
        weight = self.config["lexical_weight"]
        if self.strategy == "dense_first":
            if not dense:
                return []
            # Normalise lexical evidence over the E5 shortlist. An unmatched
            # candidate keeps its semantic contribution and can still be returned.
            ids = {h.doc_id for h in dense}
            lexical = [h for h in self.lexical.relevance_scores(request) if h.doc_id in ids]
            scores = {h.doc_id: h.score for h in relative_scores(lexical)}
            hits = [SearchHit(h.doc_id, weight * scores.get(h.doc_id, 0.0) +
                              (1 - weight) * max(0.0, min(1.0, h.score))) for h in dense]
            return sorted(hits, key=lambda h: -h.score)

        lexical = self.lexical.search(request, self.depth)
        constant = self.config["rrf_constant"]
        fused = {}
        for hits, part in ((lexical, weight), (dense, 1 - weight)):
            for rank, hit in enumerate(hits, 1):
                fused[hit.doc_id] = fused.get(hit.doc_id, 0.0) + part * (constant + 1) / (constant + rank)
        return [SearchHit(doc_id, score) for doc_id, score in
                sorted(fused.items(), key=lambda item: (-item[1], item[0]))]
