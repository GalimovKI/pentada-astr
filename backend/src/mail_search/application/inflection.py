"""Resolve a few Russian part-of-speech ambiguities from adjacent words."""
from functools import lru_cache
from collections import Counter

from pymorphy3 import MorphAnalyzer

from .derivational_stemmer import PROPER_TAGS


@lru_cache(maxsize=4096)
def likely_lemmas(word: str, morph: MorphAnalyzer) -> tuple[str, ...]:
    """Rank remaining analyses by pymorphy's probabilities, including predictions for unseen words."""
    parses = morph.parse(word)
    if parses[0].tag.grammemes & PROPER_TAGS:
        return ()
    scores = Counter()
    for p in parses:
        if p.tag.POS and not p.tag.grammemes & PROPER_TAGS:
            scores[p.normal_form] += p.score
    if word in scores:
        return (word,)
    return tuple(lemma for lemma, _ in scores.most_common(3))


@lru_cache(maxsize=4096)
def contextual_lemma(word: str, previous: str, following: str, morph: MorphAnalyzer) -> str | None:
    if not (previous or following) or not morph.word_is_known(word):
        return None
    readings = morph.parse(word)
    if len({p.normal_form for p in readings}) < 2 or any(p.tag.grammemes & PROPER_TAGS for p in readings):
        return None

    before = morph.parse(previous)[0] if previous and morph.word_is_known(previous) else None
    after = morph.parse(following) if following and morph.word_is_known(following) else []
    if before and before.tag.POS == "PREP" and before.score >= 0.9:
        # A preposition selects a nominal in an oblique case, e.g. «из стали».
        candidates = [p for p in readings if p.tag.POS in {"NOUN", "ADJF"} and p.tag.case != "nomn"]
    elif (before and before.tag.POS == "NPRO" and before.tag.case == "nomn"
          and after and all(p.tag.POS == "INFN" for p in after)):
        # «Они стали работать»: plural finite verb between subject and infinitive.
        candidates = [p for p in readings if p.tag.POS == "VERB" and p.tag.number == before.tag.number]
    elif after and all(p.tag.POS == "NOUN" and not p.tag.grammemes & PROPER_TAGS for p in after):
        # «Новые посылочки»: both words must admit the same case and number.
        candidates = [p for p in readings if p.tag.POS == "ADJF" and any(
            p.tag.number == noun.tag.number and p.tag.case == noun.tag.case
            and (p.tag.number == "plur" or p.tag.gender == noun.tag.gender) for noun in after)]
    else:
        return None
    lemmas = {p.normal_form for p in candidates}
    return lemmas.pop() if len(lemmas) == 1 else None
