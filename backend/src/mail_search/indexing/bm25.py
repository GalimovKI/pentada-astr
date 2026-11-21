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


@dataclass(frozen=True)
class CorpusStatistics:
    document_count: int
    document_frequency: Counter[str]
    average_length: float


def build_corpus_statistics(boxes: dict[str, MailboxIndex]) -> CorpusStatistics:
    document_frequency: Counter[str] = Counter()
    document_count = 0
    total_length = 0
    for index in boxes.values():
        document_count += len(index.lengths)
        total_length += sum(index.lengths.values())
        document_frequency.update({term: len(entries) for term, entries in index.postings.items()})
    average_length = total_length / max(1, document_count) or 1.0
    return CorpusStatistics(document_count, document_frequency, average_length)


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
