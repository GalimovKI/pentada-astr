"""Conservative Russian mail search alternatives, including cross-POS derivations."""
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
import re

from pymorphy3 import MorphAnalyzer
from ..search.dates import RUSSIAN_DATE

# Keep structured tokens literal, including identifiers and addresses.
TOKENS = re.compile(r"(?:https?://|www\.)[^\s]+|[\w@#]+(?:[./@:+#'’–—-]+[\w@#]+)*", re.I)
ABBREVIATION_CONTEXT = re.compile(r"\.\s+(?:[а-яё0-9]|\()")


@dataclass(frozen=True)
class Replacement:
    start: int
    end: int
    original: str
    replacement: str


@lru_cache(maxsize=1)
def russian_morphology() -> MorphAnalyzer:
    return MorphAnalyzer()


def editable_tokens(query: str) -> Iterator[re.Match[str]]:
    for token in TOKENS.finditer(query):
        word = token.group().lower()
        if (query.startswith(".", token.end()) and RUSSIAN_TOKEN.fullmatch(word)
                and word[-1] in "бвгджзйклмнпрстфхцчшщ"
                and (ABBREVIATION_CONTEXT.match(query, token.end()) or re.search(r"\d\s+$", query[:token.start()]))):
            # A consonant-final dictionary prefix before a period inside a phrase
            # can be a truncated word, e.g. «кислородн. датчика».
            morph = russian_morphology()
            if not morph.word_is_known(word) and next(morph.iter_known_word_parses(word), None):
                continue
            if any(p.is_known and "Abbr" in p.tag for p in morph.parse(word)):
                continue
        yield token


# A noun and representative surface forms also work in the unstemmed BM25 preset.
# Keys are lemmas: pymorphy recognises their inflected forms in user input.
FAMILIES = (
    (("штраф", "штрафик", "оштрафовали"), ("штраф", "штрафик", "штрафчик", "оштрафовать", "штрафовать")),
    (("оплата", "платёж", "оплатили"), ("оплата", "платёж", "платёжка", "оплатить", "оплачивать")),
    (("доставка", "доставили"), ("доставка", "доставить", "доставлять")),
    (("отчёт", "отчётик"), ("отчёт", "отчётик")),
    (("договор", "договорчик"), ("договор", "договорчик")),
)
FAMILY_WORDS = frozenset(word for forms, lemmas in FAMILIES for word in (*forms, *lemmas))
FAMILY_BY_LEMMA = {lemma.replace("ё", "е"): forms for forms, lemmas in FAMILIES for lemma in lemmas}

PROPER_TAGS = {"Name", "Surn", "Patr", "Geox", "Orgn", "Abbr", "Trad"}
CONTENT_POS = {"NOUN", "ADJF", "ADJS", "VERB", "INFN", "PRTF", "PRTS", "GRND"}
RUSSIAN_TOKEN = re.compile(r"[а-яё]{3,32}")
# Productive colloquialisms missing from the dictionary, including oblique and plural forms.
PRODUCTIVE_DIMINUTIVE = re.compile(
    r"(?P<root>[а-яё]{3,}?)(?:(?P<masc>чик|ик)(?:ом|ами|ам|ах|ов|[ауеи])?"
    r"|(?:оч|еч)(?:к(?:ами|ам|ах|ой|ою|[ауеи])|ек))"
)


@lru_cache(maxsize=1)
def diminutive_lexicon() -> dict[str, str]:
    with files(__package__).joinpath("ru_diminutives.tsv").open(encoding="utf-8") as source:
        return dict(line.rstrip("\n").split("\t") for line in source if line.strip())


@lru_cache(maxsize=4096)
def diminutive_base(word: str) -> str | None:
    """Prefer attested derivations. Infer a base only for out-of-dictionary forms."""
    if not RUSSIAN_TOKEN.fullmatch(word):
        return None
    morph = russian_morphology()
    lexicon = diminutive_lexicon()
    if morph.word_is_known(word):
        # Other readings (e.g. «гвоздик» as the plural genitive of «гвоздика»)
        # and confirmed names are important evidence against silent replacement.
        parses = morph.parse(word)
        if any(p.tag.POS != "NOUN" or p.tag.grammemes & PROPER_TAGS for p in parses):
            return None
        bases = {lexicon.get(p.normal_form) for p in parses}
        return bases.pop() if len(bases) == 1 else None

    if word in lexicon:
        return lexicon[word]
    match = PRODUCTIVE_DIMINUTIVE.fullmatch(word)
    if not match:
        return None
    root = match["root"]
    endings = ("", "ь", "й") if match["masc"] else ("ка", "а")
    gender = "masc" if match["masc"] else "femn"
    bases = set()
    for ending in endings:
        candidate = root + ending
        if not morph.word_is_known(candidate):
            continue
        for p in morph.parse(candidate):
            if (p.is_known and p.tag.POS == "NOUN" and p.tag.gender == gender
                    and not p.tag.grammemes & PROPER_TAGS
                    and p.normal_form.replace("ё", "е") == candidate.replace("ё", "е")):
                bases.add(p.normal_form)
    return bases.pop() if len(bases) == 1 else None


@lru_cache(maxsize=4096)
def word_forms(word: str, standalone: bool) -> tuple[str, ...]:
    if not RUSSIAN_TOKEN.fullmatch(word):
        return ()
    family = FAMILY_BY_LEMMA.get(word.replace("ё", "е"))
    if family:
        return family
    parses = russian_morphology().parse(word)
    family = FAMILY_BY_LEMMA.get(parses[0].normal_form.replace("ё", "е"))
    if family:
        return family
    base = diminutive_base(word)
    if base:
        return (base,)
    lemma = parses[0].normal_form
    if lemma != word and all(p.is_known and p.tag.POS in CONTENT_POS and p.normal_form == lemma
                             and not p.tag.grammemes & PROPER_TAGS for p in parses):
        # Inside a sentence preserve the original syntax and ranking first. Use lemmas
        # as a fallback, e.g. for an unstemmed engine or an irregular inflection.
        return (lemma,) if standalone else (word, lemma)
    return ()


@dataclass(frozen=True)
class WordForms:
    start: int
    end: int
    original: str
    forms: tuple[str, ...]


def query_words(query: str) -> list[WordForms]:
    words = []
    dates = RUSSIAN_DATE.finditer(query)
    date = next(dates, None)
    for token in editable_tokens(query):
        while date and date.end() <= token.start():
            date = next(dates, None)
        if date and date.start() <= token.start() < date.end():
            continue
        text = token.group()
        initial = text.istitle() and not query[:token.start()].strip()
        if not (initial or text.islower()):
            continue
        forms = word_forms(text.lower(), query.strip() == text)
        if forms:
            words.append(WordForms(token.start(), token.end(), text,
                                   tuple(f.capitalize() for f in forms) if initial else forms))
    return words


def search_queries(query: str) -> tuple[str, ...]:
    """Canonical search first, then the corrected literal and other family members."""
    words = query_words(query)
    variants = []
    for index in range(max((len(word.forms) for word in words), default=0)):
        # Each alternative keeps the other search terms and date/participant context intact.
        alternative = query
        for word in reversed(words):
            form = word.forms[index] if index < len(word.forms) else word.forms[0]
            alternative = alternative[:word.start] + form + alternative[word.end:]
        if alternative not in variants and len(alternative) <= 4000:
            variants.append(alternative)
        if index == 0 and query not in variants:
            variants.append(query)
    return tuple(variants) if variants else (query,)
