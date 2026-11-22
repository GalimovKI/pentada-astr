"""Select a literal passage from a search hit. Offsets use browser UTF-16 units."""
import re

from ..indexing.text import tokenize_stemmed
from ..search.bm25 import LEADING_COMMAND, MAIL_INTRO

WORD = re.compile(r"[^\W_]+")
LABEL = re.compile(r"^(от|отправитель|from|кому|to|тема|subject|текст письма):[ \t]*", re.I)
STOP = set(tokenize_stemmed("в во с со от до на для по под про об из за мне о и к а я"))


def query_terms(content):
    content = MAIL_INTRO.sub("", LEADING_COMMAND.sub("", content, count=1), count=1)
    return set(tokenize_stemmed(content)) - STOP


def utf16_length(text):
    return len(text.encode("utf-16-le")) // 2


def find_passage(text, terms):
    if not terms:
        return None
    best = None
    best_score = None
    for line_match in re.finditer(r"[^\r\n]+", text):
        line = line_match[0]
        label = LABEL.match(line)
        content_start = label.end() if label else 0
        header = bool(label and label[1].lower() != "текст письма")
        matches = []
        for word in WORD.finditer(line, content_start):
            if len(word[0]) > 96:
                continue
            stems = tokenize_stemmed(word[0])
            if stems and stems[0] in terms:
                matches.append((word.start(), word.end(), stems[0]))
        for i, (start, _, _) in enumerate(matches):
            selected = []
            j = i
            while j < len(matches) and matches[j][1] - start <= 100:
                selected.append(matches[j])
                j += 1
            score = (len({stem for _, _, stem in selected}), not header,
                     -(selected[-1][1] - start))
            if best_score is not None and score <= best_score:
                continue
            best = (line_match.start(), line, content_start, selected)
            best_score = score
    if best is None:
        return None
    base, line, content_start, selected = best
    first, last = selected[0][0], selected[-1][1]
    left = max(content_start, first - 30)
    if left > content_start and not line[left - 1].isspace():
        while left < first and not line[left].isspace():
            left += 1
    while left < first and line[left].isspace():
        left += 1
    right = min(len(line), left + 145)
    if right < len(line) and not line[right].isspace():
        while right > last and not line[right - 1].isspace():
            right -= 1
    while right > last and line[right - 1].isspace():
        right -= 1
    return dict(text=line[left:right], offset=utf16_length(text[:base + left]),
                ranges=[(utf16_length(line[left:a]), utf16_length(line[left:b]))
                        for a, b, _ in selected])
