"""Learn suffix-to-suffix edits for Russian diminutive nouns from lemma pairs."""
from collections import Counter, defaultdict
from collections.abc import Iterable
from functools import lru_cache
from os.path import commonprefix
import re

from pymorphy3 import MorphAnalyzer


MIN_EXAMPLES = 3
PROPER_TAGS = {"Name", "Surn", "Patr", "Geox", "Orgn", "Abbr", "Trad"}
RUSSIAN_NOUN = re.compile(r"[а-яё]{3,32}")


@lru_cache(maxsize=8192)
def _base_nouns(candidate: str, morphology: MorphAnalyzer) -> frozenset[str]:
    if not morphology.word_is_known(candidate):
        return frozenset()
    return frozenset(
        p.normal_form for p in morphology.parse(candidate)
        if p.is_known and p.tag.POS == "NOUN" and not p.tag.grammemes & PROPER_TAGS
        and p.normal_form.replace("ё", "е") == candidate
    )


class SuffixStemmer:
    def __init__(self, rules: dict[str, dict[str, int]], suffix_signals: frozenset[str]):
        self.rules = rules
        self.suffix_signals = suffix_signals
        self.lengths = sorted({len(suffix) for suffix in rules}, reverse=True)

    def may_match(self, word: str) -> bool:
        """Cheap gate for speculative corrections, including declined nouns."""
        if not RUSSIAN_NOUN.fullmatch(word):
            return False
        word = word.replace("ё", "е")
        return any(word[i:i+2] in self.suffix_signals
                   for i in range(max(2, len(word) - 9), len(word) - 1))

    @lru_cache(maxsize=8192)
    def predict_lemma(self, lemma: str, morphology: MorphAnalyzer, *, novel: bool = False) -> str | None:
        """Predict a base using shared training edits, even for an unseen lemma."""
        word = lemma.replace("ё", "е")
        for length in self.lengths:
            if len(word) - length < 2:
                continue
            edits = self.rules.get(word[-length:])
            if not edits:
                continue
            prefix = word[:-length]
            scores = Counter()
            # A weak generic edit is poor evidence for a novel word: dropping
            # «ка» from a technical noun like «монтажка» changes its meaning.
            minimum_support = sum(edits.values()) * 0.1 if novel and length <= 2 else 0
            for ending, count in edits.items():
                if count < minimum_support:
                    continue
                for base in _base_nouns(prefix + ending, morphology):
                    scores[base] += count
            if scores:
                best = scores.most_common(2)
                if len(best) == 1 or best[0][1] >= 3 * best[1][1]:
                    return best[0][0]
                return None
        return None

    @lru_cache(maxsize=8192)
    def predict(self, word: str, morphology: MorphAnalyzer) -> str | None:
        """Handle novel words in context. Known homonyms need lexical evidence."""
        if not self.may_match(word) or morphology.word_is_known(word):
            return None
        parses = morphology.parse(word)
        heads = {p.normal_form for p in parses
                 if p.tag.POS == "NOUN" and not p.tag.grammemes & PROPER_TAGS}
        if not heads:
            # On novel oblique forms the only predicted reading can be a name
            # even though its nominative (e.g. «складик») has a common-noun reading.
            heads = {p.normal_form for p in parses if p.tag.POS == "NOUN"
                     and any(h.tag.POS == "NOUN" and not h.tag.grammemes & PROPER_TAGS
                             for h in morphology.parse(p.normal_form))}
        bases = {base for head in heads if (base := self.predict_lemma(head, morphology, novel=True))}
        return bases.pop() if len(bases) == 1 else None


def fit_suffix_stemmer(pairs: Iterable[tuple[str, str]]) -> SuffixStemmer:
    """Count suffix rewrites backed by multiple distinct examples.

    Up to two preceding letters supply context for an edit. At inference the
    longest supported suffix wins, with counts breaking ties between edits.
    """
    counts = defaultdict(Counter)
    signals = Counter()
    examples = {(word.replace("ё", "е"), base.replace("ё", "е")) for word, base in pairs}
    for word, base in examples:
        common = len(commonprefix((word, base)))
        if common < 2 or len(word) - common < 2:
            continue
        suffix = word[common:]
        signals[suffix[:2]] += 1
        for start in range(max(2, common - 2), common + 1):
            counts[word[start:]][base[start:]] += 1
    rules = {
        suffix: {ending: count for ending, count in edits.items() if count >= MIN_EXAMPLES}
        for suffix, edits in counts.items() if max(edits.values()) >= MIN_EXAMPLES
    }
    return SuffixStemmer(rules, frozenset(s for s, count in signals.items() if count >= MIN_EXAMPLES))
