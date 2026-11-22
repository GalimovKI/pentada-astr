"""Extract unambiguous Russian noun diminutives from two Kaikki Wiktionary editions."""
import argparse
from collections.abc import Iterator
import json
from pathlib import Path
import re
import unicodedata


RUSSIAN = re.compile(r"[а-яё]+")
RU_GLOSS = re.compile(r"(?:разг\. )?уменьш\.(?:-ласк\.)? (?:к|от) ([а-яё]+)(?:; то же, что \1)?")

# Productive, unambiguous mail vocabulary missing from both source snapshots.
# Only use these if neither edition has a conflicting sense or base.
MAIL_DIMINUTIVES = {
    "доставочка": "доставка",
    "заказик": "заказ",
    "упаковочка": "упаковка",
}


def unaccent(word: str) -> str:
    return unicodedata.normalize("NFC", word.replace("\u0301", ""))


def diminutive_base(sense: dict, edition: str) -> str | None:
    if edition == "ru":
        glosses = sense.get("glosses", [])
        if len(glosses) == 1:
            match = RU_GLOSS.fullmatch(unaccent(glosses[0]))
            if match:
                return match[1]
        return None
    if "diminutive" not in sense.get("tags", []):
        return None
    references = sense.get("form_of", [])
    if len(references) != 1:
        return None
    base = unaccent(references[0]["word"])
    return base if RUSSIAN.fullmatch(base) else None


def extract(en_source: Path, ru_source: Path) -> dict[str, str]:
    candidates: dict[str, tuple[str, str]] = {}
    excluded: set[str] = set()
    common_nouns: set[str] = set()
    for source, edition in ((en_source, "en"), (ru_source, "ru")):
        for entry in records(source):
            if entry.get("lang_code") != "ru":
                continue
            word = unaccent(entry["word"])
            # Search accepts ё written as е, so reject homographs in either spelling.
            key = word.lower().replace("ё", "е")
            if not RUSSIAN.fullmatch(key):
                continue
            senses = entry.get("senses", [])
            if entry["pos"] != "noun" or not word.islower() or not senses:
                excluded.add(key)
                continue
            if any(not {"form-of", "alt-of", "no-gloss"}.intersection(s.get("tags", [])) for s in senses):
                common_nouns.add(word)
            # A second sense, homograph or competing base disqualifies the word.
            for sense in senses:
                base = diminutive_base(sense, edition)
                previous = candidates.get(key)
                if base is None or base == word or (previous and previous[1] != base):
                    excluded.add(key)
                elif previous is None or "ё" in word:
                    candidates[key] = (word, base)
    for word, base in MAIL_DIMINUTIVES.items():
        candidates.setdefault(word, (word, base))
    return {
        word: base for key, (word, base) in candidates.items()
        if key not in excluded and base in common_nouns
    }


def records(source: Path) -> Iterator[dict]:
    with source.open(encoding="utf-8") as lines:
        for line in lines:
            yield json.loads(line)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("en_jsonl", type=Path)
    parser.add_argument("ru_jsonl", type=Path)
    parser.add_argument("tsv", type=Path)
    args = parser.parse_args()
    pairs = extract(args.en_jsonl, args.ru_jsonl)
    with args.tsv.open("w", encoding="utf-8", newline="\n") as output:
        for word, base in sorted(pairs.items()):
            output.write(f"{word}\t{base}\n")
