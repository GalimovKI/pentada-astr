import re
from datetime import date, timedelta

from ..indexing.text import normalize

MONTHS = {name: i for i, name in enumerate(("января", "февраля", "марта", "апреля", "мая",
          "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"), 1)}
RUSSIAN_DATE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})(?:\s+года)?\b", re.I)
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
RELATIVE = re.compile(r"\b(позавчера|вчера|сегодня)\b")
RELATIVE_OFFSETS = {"сегодня": 0, "вчера": 1, "позавчера": 2}

NUMERIC_DATE = re.compile(r"\b(\d{1,2})[.](\d{1,2})[.](\d{4})\b")
CONTEXT_RELATIVE = re.compile(r"\b(позавчера|вчера|сегодня)(?:шн[а-я]+)?\b")
RECEIPT_BEFORE = re.compile(
    r"\b(?:получ[а-я]*|присла[а-я]*|поступ[а-я]*|приш[а-я]*|письм[а-я]*\s+(?:за|от))\s+(?:мне\s+)?$"
)
RECEIPT_AFTER = re.compile(r"^\s+(?:получ[а-я]*|присла[а-я]*|поступ[а-я]*|приш[а-я]*|писал[а-я]*)\b")
EVENT_BEFORE = re.compile(r"\b(?:на|до|к)\s+$")
RANGE_AFTER = re.compile(r"^\s*(?:[-–—]|по\b|до\b)\s*\d")


def target_day(text: str, anchor: date) -> tuple[date | None, str]:
    """Recognize a single day. Ambiguous/multiple dates are left to lexical search."""
    text = normalize(text)
    matches = []
    for match in RELATIVE.finditer(text):
        delta = RELATIVE_OFFSETS[match[1]]
        matches.append((anchor - timedelta(days=delta), match.span()))
    for match in RUSSIAN_DATE.finditer(text):
        matches.append((date(int(match[3]), MONTHS[match[2]], int(match[1])), match.span()))
    for match in ISO_DATE.finditer(text):
        matches.append((date.fromisoformat(match[0]), match.span()))
    if len(matches) != 1:
        return None, text
    day, (start, end) = matches[0]
    return day, text[:start] + " " + text[end:]


def receipt_day(text: str, anchor: date) -> tuple[date | None, str]:
    """Use an explicit receipt day, keeping event dates in the searchable text."""
    text = normalize(text)
    matches: list[tuple[date, int, int]] = []
    for pattern in (ISO_DATE, RUSSIAN_DATE, NUMERIC_DATE, CONTEXT_RELATIVE):
        for match in pattern.finditer(text):
            start, end = match.span()
            prefix = RECEIPT_BEFORE.search(text[:start])
            has_receipt_context = prefix is not None or RECEIPT_AFTER.search(text[end:])
            if RANGE_AFTER.match(text[end:]):
                continue
            if not has_receipt_context:
                if pattern is not CONTEXT_RELATIVE or EVENT_BEFORE.search(text[:start]):
                    continue
            try:
                if pattern is CONTEXT_RELATIVE:
                    day = anchor - timedelta(days=RELATIVE_OFFSETS[match[1]])
                elif pattern is ISO_DATE:
                    day = date.fromisoformat(match[0])
                elif pattern is NUMERIC_DATE:
                    day = date(int(match[3]), int(match[2]), int(match[1]))
                else:
                    day = date(int(match[3]), MONTHS[match[2]], int(match[1]))
            except (ValueError, OverflowError):
                return None, text
            matches.append((day, prefix.start() if prefix else start, end))
    if len(matches) != 1:
        return None, text
    day, start, end = matches[0]
    return day, text[:start] + " " + text[end:]
