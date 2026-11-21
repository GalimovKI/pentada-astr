"""In-process latency diagnostics; a server load test is a separate future step."""

import math
from collections.abc import Sequence


def percentile(values: Sequence[float], quantile: float) -> float | None:
    """Empirical nearest-rank percentile; 99 observations make p99 their maximum."""
    if not 0 < quantile <= 1:
        raise ValueError("quantile must be in (0, 1]")
    if not values:
        return None
    return sorted(values)[math.ceil(quantile * len(values)) - 1]


def latency_summary(durations: dict[str, float]) -> dict:
    values = list(durations.values())
    return {
        "scope": "in_process_engine_call", "mode": "sequential_one_pass_no_explicit_warmup",
        "unit": "ms", "samples": len(values), "percentile_method": "nearest_rank",
        "p50": percentile(values, 0.5), "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99), "max": max(values) if values else None,
        "official_server_p99_measured": False,
    }
