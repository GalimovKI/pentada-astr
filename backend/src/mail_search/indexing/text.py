import re
import unicodedata


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")


def tokenize(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", normalize(text))
