import re
from datetime import date, timedelta

from ..indexing.text import normalize

MONTHS = {name: i for i, name in enumerate(("января", "февраля", "марта", "апреля", "мая",
          "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"), 1)}
RUSSIAN_DATE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})(?:\s+года)?\b")
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
RELATIVE = re.compile(r"\b(позавчера|вчера|сегодня)\b")


def target_day(text: str, anchor: date) -> tuple[date | None, str]:
    """Recognize a single day. Ambiguous/multiple dates are left to lexical search."""
    text = normalize(text)
    matches = []
    for match in RELATIVE.finditer(text):
        delta = {"сегодня": 0, "вчера": 1, "позавчера": 2}[match[1]]
        matches.append((anchor - timedelta(days=delta), match.span()))
    for match in RUSSIAN_DATE.finditer(text):
        matches.append((date(int(match[3]), MONTHS[match[2]], int(match[1])), match.span()))
    for match in ISO_DATE.finditer(text):
        matches.append((date.fromisoformat(match[0]), match.span()))
    if len(matches) != 1:
        return None, text
    day, (start, end) = matches[0]
    return day, text[:start] + " " + text[end:]
