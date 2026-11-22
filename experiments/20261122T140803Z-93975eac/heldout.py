"""5-fold OOF with derivational families and all homographs kept together."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import subprocess

from mail_search.application.derivational_stemmer import fit_suffix_stemmer
from mail_search.application.word_forms import russian_morphology
from mail_search.indexing.text import tokenize_stemmed


def normalized(word):
    return word.casefold().replace("ё", "е")


def family_groups(pairs):
    graph = defaultdict(set)
    for form, base in pairs:
        x, y = normalized(form), normalized(base)
        graph[x].add(y)
        graph[y].add(x)
    groups = {}
    for node in sorted(graph):
        if node in groups:
            continue
        stack = [node]
        while stack:
            word = stack.pop()
            if word in groups:
                continue
            groups[word] = node
            stack.extend(graph[word])
    return groups


def fold_of(label):
    return int(hashlib.sha256(("smartmail-diminutives-v1:" + label).encode()).hexdigest(), 16) % 5


NEGATIVES = [
    "график", "ручка", "заказчик", "переводчик", "гвоздик", "поводок",
    "дворник", "открытка", "отпускник", "холодильник", "заявка", "проводник",
    "техник", "датчик", "сотрудник", "страховщик", "чайник", "графин",
    "станочник", "сантехник", "дневник", "срок", "тариф", "налог",
]
PROBES = {
    "штрафик": "штраф", "штрафчиком": "штраф", "штрафиках": "штраф", "штрафчиками": "штраф",
    "заказик": "заказ", "складик": "склад", "контейнерчиками": "контейнер",
    "доставочка": "доставка", "упаковочка": "упаковка", "возвратик": "возврат",
}


def ratio(numerator, denominator):
    return numerator/denominator if denominator else None


def aggregate(rows, key):
    n = len(rows)
    predictions = [row for row in rows if row[key] is not None]
    successes = sum(normalized(row[key]) == normalized(row["target"]) for row in predictions)
    return dict(total=n, predicted=len(predictions), correct=successes, incorrect=len(predictions)-successes,
                coverage=ratio(len(predictions),n), exact_overall=ratio(successes,n),
                precision_on_predictions=ratio(successes,len(predictions)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tsv",type=Path)
    parser.add_argument("output",type=Path)
    args = parser.parse_args()
    morph = russian_morphology()
    raw = [line.split("\t") for line in args.tsv.read_text().splitlines() if line]
    manual = {"доставочка", "заказик", "упаковочка"}
    pairs = [(word,base) for word,base in raw if word not in manual and not "штраф" in word and not "штраф" in base]
    groups = family_groups(pairs)
    rows, fold_sizes = [], []
    for fold in range(5):
        train = [(w,b) for w,b in pairs if fold_of(groups[normalized(b)]) != fold]
        test = [(w,b) for w,b in pairs if fold_of(groups[normalized(b)]) == fold]
        train_words = {normalized(w) for pair in train for w in pair}
        test_words = {normalized(w) for pair in test for w in pair}
        assert not train_words.intersection(test_words)
        model = fit_suffix_stemmer(train)
        fold_sizes.append(dict(fold=fold,train=len(train),test=len(test),overlap=0))
        for word,base in test:
            rows.append(dict(fold=fold,known=morph.word_is_known(word),word=word,target=base,
                             generated=model.predict_lemma(word,morph),guarded=model.predict(word,morph),
                             snowball_same=tokenize_stemmed(word)==tokenize_stemmed(base)))
    assert len(rows) == len(pairs)
    full = fit_suffix_stemmer(pairs)
    diagnostics = {}
    for word,base in PROBES.items():
        diagnostics[word] = dict(expected=base,generated=full.predict_lemma(word,morph),
                                 guarded=full.predict(word,morph),in_train=word in dict(pairs),
                                 stems=[tokenize_stemmed(word), tokenize_stemmed(base)])
    controls = {w: {"raw":full.predict_lemma(w,morph),"guarded":full.predict(w,morph)} for w in NEGATIVES}
    report = dict(tsv_sha256=hashlib.sha256(args.tsv.read_bytes()).hexdigest(),input_pairs=len(raw),n_pairs=len(pairs),
                  excluded=len(raw)-len(pairs),n_families=len(set(groups.values())),folds=fold_sizes,
                  snowball_same_count=sum(r["snowball_same"] for r in rows),oof_lemma=aggregate(rows,"generated"),
                  oof_guarded=aggregate(rows,"guarded"),probes=diagnostics,negative_controls=controls,
                  n_known=sum(r["known"] for r in rows),oof_lemma_known=aggregate([r for r in rows if r["known"]],"generated"),
                  oof_lemma_oov=aggregate([r for r in rows if not r["known"]],"generated"),
                  model_git_sha=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip())
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/"holdout.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    (args.output/"holdout_predictions.jsonl").write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in rows))
    print(json.dumps({k:report[k] for k in ["n_pairs","n_families","n_known","snowball_same_count","oof_lemma","oof_guarded"]}))
    print(report["probes"], report["negative_controls"])


if __name__ == "__main__":
    main()
