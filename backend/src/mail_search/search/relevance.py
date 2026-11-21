"""Comparable lexical strength within one query; independent of rank position."""
from ..domain.models import SearchHit


def relative_scores(hits):
    peak = max((hit.score for hit in hits), default=0)
    # Date-only searches assign equal zero text scores to exact receipt-day matches.
    return [SearchHit(hit.doc_id, hit.score / peak if peak else 1.0) for hit in hits]
