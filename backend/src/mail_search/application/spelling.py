"""Conservative single-edit suggestions using local Russian and English word frequencies."""
from dataclasses import dataclass
from functools import lru_cache
import re

from pymorphy3 import MorphAnalyzer
from spellchecker import SpellChecker

# Scan structured tokens as a whole so words inside addresses, URLs and IDs stay literal.
TOKENS = re.compile(r"(?:https?://|www\.)[^\s]+|[\w@#]+(?:[./@:+#'’–—-]+[\w@#]+)*", re.I)
RU = re.compile("[а-яё]{5,28}")
EN = re.compile("[a-z]{5,28}")


@dataclass(frozen=True)
class Replacement:
    start: int
    end: int
    original: str
    replacement: str


@lru_cache(maxsize=2)
def dictionary(language: str) -> SpellChecker:
    return SpellChecker(language=language, distance=1)


@lru_cache(maxsize=1)
def russian_morphology() -> MorphAnalyzer:
    return MorphAnalyzer()


@lru_cache(maxsize=4096)
def replacement_for(word: str, language: str) -> str | None:
    checker = dictionary(language)
    if word in checker or language == "ru" and russian_morphology().word_is_known(word):
        return None

    # Adjacent transpositions change no letters and are particularly useful in short queries.
    transposed = {word[:i] + word[i:i+2][::-1] + word[i+2:] for i in range(len(word) - 1)}
    transposed.discard(word)
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


def correct_query(query: str) -> tuple[str, list[Replacement]]:
    changes = []
    corrected_length = len(query)
    pieces, cursor = [], 0
    for token in TOKENS.finditer(query):
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
