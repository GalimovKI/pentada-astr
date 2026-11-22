"""Conservative Russian mail search alternatives, including cross-POS derivations."""
from dataclasses import dataclass
from functools import lru_cache
import re

from pymorphy3 import MorphAnalyzer

# Keep structured tokens literal, including identifiers and addresses.
TOKENS = re.compile(r"(?:https?://|www\.)[^\s]+|[\w@#]+(?:[./@:+#'’–—-]+[\w@#]+)*", re.I)


@dataclass(frozen=True)
class Replacement:
    start: int
    end: int
    original: str
    replacement: str


@lru_cache(maxsize=1)
def russian_morphology() -> MorphAnalyzer:
    return MorphAnalyzer()


# A noun and representative surface forms also work in the unstemmed BM25 preset.
# Keys are lemmas: pymorphy recognises their inflected forms in user input.
FAMILIES = (
    (("штраф", "штрафик", "оштрафовали"), ("штраф", "штрафик", "штрафчик", "оштрафовать", "штрафовать")),
    (("оплата", "платёж", "оплатили"), ("оплата", "платёж", "платёжка", "оплатить", "оплачивать")),
    (("доставка", "доставили"), ("доставка", "доставить", "доставлять")),
    (("отчёт", "отчётик"), ("отчёт", "отчётик")),
    (("договор", "договорчик"), ("договор", "договорчик")),
)
FAMILY_BY_LEMMA = {lemma.replace("ё", "е"): forms for forms, lemmas in FAMILIES for lemma in lemmas}


@lru_cache(maxsize=4096)
def word_forms(word: str, standalone: bool) -> tuple[str, ...]:
    if not re.fullmatch(r"[а-яё]{3,32}", word):
        return ()
    family = FAMILY_BY_LEMMA.get(word.replace("ё", "е"))
    if family:
        return family
    parses = russian_morphology().parse(word)
    family = FAMILY_BY_LEMMA.get(parses[0].normal_form.replace("ё", "е"))
    if family:
        return family
    # For single-word searches, a dictionary-backed unambiguous common noun
    # can be searched in its nominative form without changing sentence context.
    if standalone and all(p.is_known and p.tag.POS == "NOUN" and
                          p.normal_form == parses[0].normal_form and
                          not p.tag.grammemes.intersection({"Name", "Surn", "Patr", "Geox", "Orgn", "Abbr"})
                          for p in parses):
        return (parses[0].normal_form,)
    return ()


@dataclass(frozen=True)
class WordForms:
    start: int
    end: int
    original: str
    forms: tuple[str, ...]


def query_words(query: str) -> list[WordForms]:
    words = []
    for token in TOKENS.finditer(query):
        text = token.group()
        initial = text.istitle() and not query[:token.start()].strip()
        if not (initial or text.islower()):
            continue
        forms = word_forms(text.lower(), query.strip() == text)
        if forms:
            words.append(WordForms(token.start(), token.end(), text,
                                   tuple(f.capitalize() for f in forms) if initial else forms))
    return words


def related_hints(query: str, cursor: int | None) -> list[Replacement]:
    for word in query_words(query):
        if word.end == (len(query) if cursor is None else cursor):
            return [Replacement(word.start, word.end, word.original, form) for form in word.forms
                    if form.casefold() != word.original.casefold()]
    return []


def related_queries(query: str) -> tuple[str, ...]:
    words = query_words(query)
    variants = []
    for index in range(max((len(word.forms) for word in words), default=0)):
        # Each alternative keeps the other search terms and date/participant context intact.
        alternative = query
        for word in reversed(words):
            form = word.forms[index] if index < len(word.forms) else word.forms[0]
            alternative = alternative[:word.start] + form + alternative[word.end:]
        if alternative != query and alternative not in variants and len(alternative) <= 4000:
            variants.append(alternative)
    return tuple(variants)
