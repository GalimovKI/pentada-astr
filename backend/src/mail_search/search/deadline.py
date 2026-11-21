from time import monotonic


SEARCH_BUDGET_SECONDS = 0.8


def check_deadline(deadline: float) -> None:
    if monotonic() >= deadline:
        raise TimeoutError("search exceeded its time budget")
