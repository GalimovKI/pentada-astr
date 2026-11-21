"""Propose text spans and classify each role without access to relevance labels."""
from dataclasses import dataclass
from datetime import timedelta
from difflib import SequenceMatcher
import re

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from mailsearch.metadata import DATE, RELATIVE, parse_date

EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
NAME = re.compile(r"\b[А-ЯЁ][а-яё]{2,}\b")
REL = re.compile(r"\b(вчерашн\w*|сегодняшн\w*|позавчера|сегодня|вчера)\b", re.I)
HEADER = re.compile(r"^(от|from|отправитель|кому|to|получатель)\s*:\s*(.+)$", re.I)
BODY = re.compile(r"^(текст письма|body)\s*:", re.I)


def headers(body):
    fields = {"sender": "", "recipient": ""}
    for line in body.splitlines()[:6]:
        if BODY.match(line):
            break
        if m := HEADER.fullmatch(line.strip()):
            field = "sender" if m[1].lower() in {"от", "from", "отправитель"} else "recipient"
            if not fields[field]:
                fields[field] = m[2].strip()
    return fields


@dataclass(frozen=True)
class Span:
    kind: str
    value: str
    start: int
    end: int


def spans(text, as_of, known_names):
    result = []
    for m in DATE.finditer(text):
        if day := parse_date(m[0]):
            result.append(Span("date", day.isoformat(), *m.span()))
    for m in REL.finditer(text):
        word = m[0].lower()
        offset = RELATIVE.get(word, 1 if word.startswith("вчерашн") else 0)
        result.append(Span("date", (as_of - timedelta(days=offset)).isoformat(), *m.span()))
    for m in EMAIL.finditer(text):
        result.append(Span("person", m[0].casefold(), *m.span()))
    for m in NAME.finditer(text):
        word = m[0].casefold()
        matches = [(SequenceMatcher(None, word, n).ratio(), n) for n in known_names if n[:3] == word[:3]]
        if matches:
            score, name = max(matches)
            if score >= 0.75:
                result.append(Span("person", name, *m.span()))
    return result


def rule_role(text, span):
    left, right = text[:span.start].casefold(), text[span.end:].casefold()
    if span.kind == "date":
        if re.search(r"(встреч\w*|билет\w* на)\s*$", left) or re.match(r"\s+встреч", right):
            return "other"
        return "receipt" if (re.search(r"(?:получ\w*|письм\w* от|присла\w*)\s*$", left)
                             or re.match(r"\s+(?:письм|почт)", right)
                             or text[span.start:span.end].casefold() in RELATIVE) else "other"
    if re.search(r"(?:\bот|писал\w*|прислал\w*)\s*$", left) or re.match(r"\s+(?:прислал|писал)", right):
        return "sender"
    if re.search(r"(?:\bдля|отправили)\s*$", left):
        return "recipient"
    return "other"


class RoleModel:
    def __init__(self, path):
        self.tokenizer = AutoTokenizer.from_pretrained(path, padding_side="left")
        self.model = AutoModelForCausalLM.from_pretrained(path, dtype=torch.bfloat16).to("cuda").eval()
        self.letters = [self.tokenizer.encode(c, add_special_tokens=False)[0] for c in "ABC"]
        if any(len(self.tokenizer.encode(c, add_special_tokens=False)) != 1 for c in "ABC"):
            raise ValueError("Expected single-token labels")

    def classify(self, pairs):
        outputs = []
        for offset in range(0, len(pairs), 16):
            batch = pairs[offset:offset+16]
            prompts, choices = [], []
            for text, span in batch:
                marked = text[:span.start] + "[" + text[span.start:span.end] + "]" + text[span.end:]
                if span.kind == "date":
                    guide = ("A = when the email arrived or was sent; B = a date of an event described "
                             "in the email; C = unclear. Examples: 'получено [вчера]' A; 'встреча [вчера]' B.")
                    choices.append(("receipt", "other", "unclear"))
                else:
                    guide = ("A = sender of the email; B = addressee of the email; C = person mentioned "
                             "or unclear. Examples: 'от [Ольги]' A; 'для [Ивана]' B; 'о [Петре]' C.")
                    choices.append(("sender", "recipient", "other"))
                messages = [dict(role="user", content=f"Classify the bracketed span in a Russian email search. {guide}\nQuery: {marked}\nAnswer with one letter only:")]
                prompts.append(self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True))
            inputs = self.tokenizer(prompts, return_tensors="pt", padding=True).to(self.model.device)
            with torch.inference_mode():
                logits = self.model(**inputs, logits_to_keep=1).logits[:, -1, self.letters].float()
                probs = torch.softmax(logits, -1).cpu().tolist()
            for labels, p in zip(choices, probs, strict=True):
                index = max(range(3), key=p.__getitem__)
                outputs.append((labels[index], p[index]))
        return outputs
