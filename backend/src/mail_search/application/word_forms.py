"""Conservative Russian mail search alternatives, including cross-POS derivations."""
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from importlib.resources import files
import re

from pymorphy3 import MorphAnalyzer
from ..search.dates import RUSSIAN_DATE, receipt_day
from .derivational_stemmer import PROPER_TAGS, SuffixStemmer, fit_suffix_stemmer
from .inflection import contextual_lemma, likely_lemmas

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


# Semantic query expansion after morphological analysis. These output variants
# also retrieve documents in the legacy, unstemmed BM25 preset.
RELATED_FORMS = {
    "штраф": ("штраф", "штрафик", "оштрафовали"),
    "оплата": ("оплата", "платёж", "оплатили"),
    "доставка": ("доставка", "доставили"),
    "отчёт": ("отчёт", "отчётик"),
    "договор": ("договор", "договорчик"),
}
RELATED_LEMMAS = {
    "оштрафовать": "штраф", "штрафовать": "штраф",
    "платёж": "оплата", "платёжка": "оплата", "оплатить": "оплата", "оплачивать": "оплата",
    "доставить": "доставка", "доставлять": "доставка",
}
CONTENT_POS = {"NOUN", "ADJF", "ADJS", "VERB", "INFN", "PRTF", "PRTS", "GRND", "COMP", "NUMR", "NPRO"}
RUSSIAN_TOKEN = re.compile(r"[а-яё]{1,64}")


@lru_cache(maxsize=1)
def diminutive_lexicon() -> dict[str, str]:
    with files(__package__).joinpath("ru_diminutives.tsv").open(encoding="utf-8") as source:
        return dict(line.rstrip("\n").split("\t") for line in source if line.strip())


@lru_cache(maxsize=1)
def suffix_stemmer() -> SuffixStemmer:
    return fit_suffix_stemmer(diminutive_lexicon().items())


@lru_cache(maxsize=4096)
def diminutive_base(word: str) -> str | None:
    if not RUSSIAN_TOKEN.fullmatch(word):
        return None
    morph = russian_morphology()
    model = suffix_stemmer()
    lexicon = diminutive_lexicon()
    if not morph.word_is_known(word):
        return model.predict(word, morph) or lexicon.get(word)
    parses = morph.parse(word)
    if any(p.tag.POS != "NOUN" or p.tag.grammemes & PROPER_TAGS for p in parses):
        return None
    heads = {p.normal_form for p in parses}
    if len(heads) != 1:
        return None
    head = heads.pop()
    attested = lexicon.get(head)
    # Only derive a known word when its diminutive reading has been confirmed.
    # «упаковочка» is an additional reviewed reading; the model supplies its base.
    if attested or head == "упаковочка":
        predicted = model.predict_lemma(head, morph)
        return predicted if predicted and (not attested or predicted == attested) else attested
    return None


def retrieval_forms(lemma: str) -> tuple[str, ...]:
    if lemma in RELATED_LEMMAS:
        # A related noun can retrieve more letters, but the verb's lemma is its infinitive.
        return tuple(dict.fromkeys((lemma, *RELATED_FORMS[RELATED_LEMMAS[lemma]])))
    return RELATED_FORMS.get(lemma, (lemma,))


@lru_cache(maxsize=4096)
def word_forms(word: str) -> tuple[str, ...]:
    if not RUSSIAN_TOKEN.fullmatch(word):
        return ()
    base = diminutive_base(word)
    if base:
        return retrieval_forms(base)
    parses = russian_morphology().parse(word)
    lemma = parses[0].normal_form
    if all(p.is_known and p.tag.POS in CONTENT_POS and p.normal_form == lemma
           and not p.tag.grammemes & PROPER_TAGS for p in parses):
        return retrieval_forms(lemma)
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
    tokens = list(editable_tokens(query))
    for index, token in enumerate(tokens):
        while date and date.end() <= token.start():
            date = next(dates, None)
        if date and date.start() <= token.start() < date.end():
            continue
        text = token.group()
        capitalized = text.istitle()
        if not (capitalized or text.islower()) or not RUSSIAN_TOKEN.fullmatch(text.lower()):
            continue
        if capitalized and any(p.is_known and p.tag.grammemes & PROPER_TAGS
                               for p in russian_morphology().parse(text.lower())):
            continue
        forms = word_forms(text.lower())
        if not forms and RUSSIAN_TOKEN.fullmatch(text.lower()) and len(tokens) > 1:
            previous = following = ""
            if index and query[tokens[index - 1].end():token.start()].isspace():
                previous = tokens[index - 1].group().lower()
            if index + 1 < len(tokens) and query[token.end():tokens[index + 1].start()].isspace():
                following = tokens[index + 1].group().lower()
            lemma = contextual_lemma(text.lower(), previous, following, russian_morphology())
            if lemma:
                forms = retrieval_forms(lemma)
        if not forms:
            forms = likely_lemmas(text.lower(), russian_morphology())
        if forms:
            words.append(WordForms(token.start(), token.end(), text,
                                   tuple(f.capitalize() for f in forms) if capitalized else forms))
    return words


def search_queries(query: str, *, query_date: date | None = None) -> tuple[str, ...]:
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
    if variants and query_date is not None:
        # A lemma such as «прийти» may lose the receipt cue present in «пришли».
        # Compare to the user's wording before choosing the primary ranked query.
        day = receipt_day(query, query_date)[0]
        variants = [v for v in variants if v == query or receipt_day(v, query_date)[0] == day]
    return tuple(variants) if variants else (query,)
