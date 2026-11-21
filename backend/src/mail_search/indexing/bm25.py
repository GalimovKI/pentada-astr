from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from ..domain.models import Document
from .text import tokenize


@dataclass(frozen=True)
class MailboxIndex:
    postings: dict[str, list[tuple[str, int]]]
    lengths: dict[str, int]
    average_length: float


def build_bm25_index(
    documents: tuple[Document, ...],
    tokenizer: Callable[[str], list[str]] = tokenize,
) -> dict[str, MailboxIndex]:
    boxes = {}
    grouped = defaultdict(list)
    for document in documents:
        grouped[document.synthetic_user].append(document)
    for user, items in grouped.items():
        postings = defaultdict(list)
        lengths = {}
        for document in items:
            tokens = tokenizer(document.doc)
            lengths[document.doc_id] = len(tokens)
            for term, frequency in Counter(tokens).items():
                postings[term].append((document.doc_id, frequency))
        boxes[user] = MailboxIndex(dict(postings), lengths, sum(lengths.values()) / len(items) or 1.0)
    return boxes
