"""Binary relevance; macro averages over queries; no official score weights."""

import math
from collections.abc import Mapping, Sequence


def metrics_at_k(ranking: Sequence[str], qrels: Mapping[str, int], k: int) -> dict[str, float]:
    if k < 1:
        raise ValueError("K must be positive")
    relevant = {did for did, relevance in qrels.items() if relevance > 0}
    gains = [int(did in relevant) for did in ranking[:k]]
    found = sum(gains)
    dcg = sum(gain / math.log2(rank + 2) for rank, gain in enumerate(gains))
    ideal = sum(1 / math.log2(rank + 2) for rank in range(min(k, len(relevant))))
    return {
        "recall": found / len(relevant) if relevant else 0.0,
        "ndcg": dcg / ideal if ideal else 0.0,
        "mrr": next((1 / (rank + 1) for rank, gain in enumerate(gains) if gain), 0.0),
    }
