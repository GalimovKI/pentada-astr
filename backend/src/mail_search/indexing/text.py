import re
import unicodedata
from functools import lru_cache

import snowballstemmer

RUSSIAN_WORD = re.compile(r"[а-я]+")


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")


def tokenize(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", normalize(text))


@lru_cache(maxsize=65_536)
def _russian_stem(token: str) -> str:
    # The Snowball instance is mutable. Give each cache miss its own instance.
    return snowballstemmer.stemmer("russian").stemWord(token)


def tokenize_stemmed(text: str) -> list[str]:
    return [_russian_stem(token) if RUSSIAN_WORD.fullmatch(token) else token for token in tokenize(text)]
