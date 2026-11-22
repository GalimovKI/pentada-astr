"""Conservative single-edit suggestions using local Russian and English word frequencies."""
from bisect import bisect_left
from functools import lru_cache
from heapq import nsmallest
from itertools import chain
import re

from spellchecker import SpellChecker

from .word_forms import (
    PROPER_TAGS, Replacement, suffix_stemmer,
    diminutive_base, editable_tokens, russian_morphology,
)

RU = re.compile("[а-яё]{3,32}")
EN = re.compile("[a-z]{3,32}")
VOWEL_CONFUSIONS = ("ао", "еэи", "иы")
VOWELS = "аеиоуыэюя"
CONSONANTS = frozenset("бвгджзклмнпрстфхцчшщ")


@lru_cache(maxsize=2)
def dictionary(language: str) -> SpellChecker:
    return SpellChecker(language=language, distance=1)


@lru_cache(maxsize=2)
def completion_words(language: str) -> tuple[str, ...]:
    return tuple(sorted(word for word in dictionary(language).word_frequency.dictionary if word.isalpha()))


@lru_cache(maxsize=2048)
def top_completions(prefix: str, language: str) -> tuple[str, ...]:
    words = completion_words(language)
    start = bisect_left(words, prefix)
    end = bisect_left(words, prefix + chr(0x10FFFF))
    frequency = dictionary(language).word_frequency
    matches = (words[i] for i in range(start, end) if words[i] != prefix)
    return tuple(nsmallest(3, matches, key=lambda word: (-frequency[word], len(word), word)))


def spelling_hints(query: str, cursor: int | None = None, *, expand_word_forms: bool = False) -> dict[str, list[Replacement]]:
    _, changes = correct_query(query, preserve_forms=expand_word_forms)
    cursor = len(query) if cursor is None else cursor
    token = next((token for token in editable_tokens(query) if token.end() == cursor), None)
    completions = []
    if token is not None:
        original = token.group()
        prefix = original.lower()
        if re.fullmatch(r"[а-яё]{3,28}", prefix):
            language = "ru"
        elif re.fullmatch(r"[a-z]{3,28}", prefix):
            language = "en"
        else:
            language = None
        if language and (original.islower() or original.istitle()):
            for word in top_completions(prefix, language):
                if len(query) + len(word) - len(original) <= 4000:
                    completions.append(Replacement(token.start(), cursor, original,
                                                   word.capitalize() if original.istitle() else word))
    if completions:
        changes = [change for change in changes if change.start != token.start()]
    return {"changes": changes, "completions": completions}


def frequent_choice(choices: set[str], checker: SpellChecker) -> str | None:
    ranked = sorted(choices, key=lambda value: (-checker.word_frequency[value], value))
    if not ranked:
        return None
    best = ranked[0]
    count = checker.word_frequency[best]
    if count >= 10 and (len(ranked) == 1 or count >= 4 * checker.word_frequency[ranked[1]]):
        return best
    return None


def plausible_substitution(word: str, candidate: str, language: str) -> bool:
    old, new = next((a, b) for a, b in zip(word, candidate) if a != b)
    rows = ("йцукенгшщзхъ", "фывапролджэ", "ячсмитьбю") if language == "ru" else (
        "qwertyuiop", "asdfghjkl", "zxcvbnm")
    if any(old + new in row or new + old in row for row in rows):
        return True
    return language == "ru" and any(old in group and new in group for group in VOWEL_CONFUSIONS)


def recognized(word: str, language: str, checker: SpellChecker) -> bool:
    return word in checker or language == "ru" and (
        russian_morphology().word_is_known(word) or diminutive_base(word) is not None
    )


def russian_vowel_correction(word: str) -> str | None:
    morphology = russian_morphology()
    # Restrict the rare-word fallback to likely vowel confusion or a missing
    # vowel between consonants. Unrestricted dictionary edits change genuine
    # out-of-vocabulary terms, e.g. «поворотник» into «подворотник».
    inserts = (word[:i] + v + word[i:] for i in range(1, len(word))
               if word[i-1] in CONSONANTS and word[i] in CONSONANTS for v in VOWELS)
    vowels = (word[:i] + v + word[i+1:] for i, c in enumerate(word)
              for group in VOWEL_CONFUSIONS if c in group for v in group if v != c)
    match = None
    for candidate in chain(vowels, inserts):
        if candidate == match:
            continue
        if morphology.word_is_known(candidate):
            if not any(p.is_known and not p.tag.grammemes & PROPER_TAGS for p in morphology.parse(candidate)):
                continue
        elif not (suffix_stemmer().may_match(candidate) and diminutive_base(candidate)):
            continue
        if match is not None:
            return None
        match = candidate
    return match


@lru_cache(maxsize=4096)
def replacement_for(word: str, language: str) -> str | None:
    checker = dictionary(language)
    if recognized(word, language, checker):
        return None

    # A repeated key has stronger evidence than an arbitrary insertion or substitution.
    drops = {word[:i] + word[i+1:] for i in range(1, len(word)) if word[i-1] == word[i]}
    repeated = [w for w in drops if recognized(w, language, checker)]
    if len(repeated) == 1:
        return repeated[0]

    swaps = {word[:i] + word[i+1] + word[i] + word[i+2:]
             for i in range(len(word) - 1) if word[i] != word[i+1]}
    candidates = (checker.candidates(word) or set()) - {word}
    common_swaps = candidates & swaps
    if len(word) <= 4:
        # A short prefix is useful as-is. For other short tokens only consider
        # internal omissions and swaps: «закз» has many unrelated one-edit neighbours.
        if not common_swaps and top_completions(word, language):
            return None
        omitted = {w for w in candidates if len(w) == len(word) + 1
                   and w[0] == word[0] and w[-1] == word[-1]}
        best_swap = frequent_choice(common_swaps, checker)
        best_insert = frequent_choice(omitted, checker)
        if best_insert and (not best_swap or
                            checker.word_frequency[best_insert] >= 2 * checker.word_frequency[best_swap]):
            return best_insert
        return best_swap

    if common_swaps:
        return frequent_choice(common_swaps, checker)
    if language == "ru":
        # OpenCorpora covers inflections and the derivation lookup covers productive
        # diminutives absent from both frequency dictionaries.
        variants = {w for w in swaps
                    if suffix_stemmer().may_match(w) and diminutive_base(w)}
        if len(variants) == 1:
            return variants.pop()
    plausible = {w for w in candidates if len(word) != len(w) or plausible_substitution(word, w, language)}
    best = frequent_choice(plausible, checker)
    if best or language != "ru":
        return best

    morphology = russian_morphology()
    inflections = {w for w in swaps if morphology.word_is_known(w)}
    if inflections:
        return inflections.pop() if len(inflections) == 1 else None
    if not candidates and len(word) >= 6:
        return russian_vowel_correction(word)
    return None


def correct_query(query: str, *, preserve_forms: bool = False) -> tuple[str, list[Replacement]]:
    changes = []
    corrected_length = len(query)
    pieces, cursor = [], 0
    for token in editable_tokens(query):
        original = token.group()
        lower = original.lower()
        language = "ru" if RU.fullmatch(lower) else "en" if EN.fullmatch(lower) else None
        # Preserve acronyms, mixed-case names and capitalised names within a phrase.
        first_title = original.istitle() and not query[:token.start()].strip()
        if language is None or not (original.islower() or first_title):
            continue
        if preserve_forms and language == "ru" and diminutive_base(lower) is not None:
            continue
        replacement = replacement_for(lower, language)
        if replacement is None:
            continue
        if first_title:
            replacement = replacement.capitalize()
        new_length = corrected_length + len(replacement) - len(original)
        if new_length > 4000:
            continue
        corrected_length = new_length
        changes.append(Replacement(token.start(), token.end(), original, replacement))
        pieces.extend((query[cursor:token.start()], replacement))
        cursor = token.end()
    pieces.append(query[cursor:])
    return "".join(pieces), changes
