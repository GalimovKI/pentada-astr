"""Conservative single-edit suggestions using local Russian and English word frequencies."""
from bisect import bisect_left
from functools import lru_cache
from heapq import nsmallest
import re

from spellchecker import SpellChecker

from .word_forms import FAMILY_WORDS, Replacement, TOKENS, query_words, russian_morphology

RU = re.compile("[а-яё]{5,28}")
EN = re.compile("[a-z]{5,28}")


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
    token = next((token for token in TOKENS.finditer(query) if token.end() == cursor), None)
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


@lru_cache(maxsize=4096)
def replacement_for(word: str, language: str) -> str | None:
    checker = dictionary(language)
    if word in checker or language == "ru" and russian_morphology().word_is_known(word):
        return None

    # Adjacent transpositions change no letters and are particularly useful in short queries.
    transposed = {word[:i] + word[i:i+2][::-1] + word[i+2:] for i in range(len(word) - 1)}
    transposed.discard(word)
    if language == "ru":
        known = transposed & FAMILY_WORDS
        if len(known) == 1:
            return next(iter(known))
    candidates = checker.candidates(word) or set()
    choices = candidates & transposed
    if language == "ru" and not choices:
        # The frequency dictionary omits some inflected forms, including «доставку».
        inflections = [value for value in transposed if russian_morphology().word_is_known(value)]
        if len(inflections) == 1:
            return inflections[0]
    choices = choices or candidates
    if not choices:
        return None
    ranked = sorted(choices, key=lambda value: (-checker.word_frequency[value], value))
    best = ranked[0]
    count = checker.word_frequency[best]
    if count < 10 or len(ranked) > 1 and count < 4 * checker.word_frequency[ranked[1]]:
        return None
    # A (possibly rare) correctly spelled name or word is easy to turn into a different word
    # by substituting one character. Only suggest this edit for neighbouring keyboard keys.
    if len(best) == len(word) and best not in transposed:
        left, right = next((a, b) for a, b in zip(word, best) if a != b)
        rows = ("йцукенгшщзхъ", "фывапролджэ", "ячсмитьбю") if language == "ru" else (
            "qwertyuiop", "asdfghjkl", "zxcvbnm")
        if not any(left + right in row or right + left in row for row in rows):
            return None
    return best


def correct_query(query: str, *, preserve_forms: bool = False) -> tuple[str, list[Replacement]]:
    protected = set()
    if preserve_forms:
        protected = {word.start for word in query_words(query)}
    changes = []
    corrected_length = len(query)
    pieces, cursor = [], 0
    for token in TOKENS.finditer(query):
        if token.start() in protected:
            continue
        original = token.group()
        lower = original.lower()
        language = "ru" if RU.fullmatch(lower) else "en" if EN.fullmatch(lower) else None
        # Preserve acronyms, mixed-case names and capitalised names within a phrase.
        first_title = original.istitle() and not query[:token.start()].strip()
        if language is None or not (original.islower() or first_title):
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
