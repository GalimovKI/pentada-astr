"""From a clean code checkout: PYTHONPATH=backend/src python check.py ARCHIVE OUTPUT_DIR."""
from dataclasses import replace
from datetime import date, datetime, timezone
from inspect import signature
import json
from pathlib import Path
import random
import re
import sys
from unittest.mock import Mock

from fastapi.testclient import TestClient
from mail_search.api.app import create_app
from mail_search.application.spelling import correct_query
from mail_search.application.word_forms import search_queries
from mail_search.core.provenance import code_version
from mail_search.core.settings import Settings
from mail_search.domain.models import SearchHit, SearchRequest
from mail_search.evaluation.runner import evaluate, run_engine, write_run
from mail_search.ingestion.dataset import load_dataset
from mail_search.search.dates import receipt_day
from mail_search.storage.repository import MessagePreview


class Store:
    def __init__(self, dataset):
        self.dataset = dataset
        self.mailboxes = sorted({d.synthetic_user for d in dataset.documents.values()})

    def import_fingerprint(self):
        return self.dataset.summary["fingerprint"]

    def list_mailboxes(self):
        return self.mailboxes

    def get_previews(self, user, ids, query_date):
        docs = [self.dataset.documents[k] for k in ids]
        assert all(d.synthetic_user == user and (not d.doc_dt or d.doc_dt <= query_date) for d in docs)
        return [MessagePreview(d.doc_id, d.synthetic_user, d.doc_dt, d.doc[:200]) for d in docs]


class Transport:
    def __init__(self, client):
        self.client = client

    def search(self, req, k):
        response = self.client.post(f"/api/v1/mailboxes/{req.synthetic_user}/search", json={
            "query": req.query, "query_date": req.query_date.isoformat(), "limit": k,
            "correct_typos": True, "expand_word_forms": True,
        })
        response.raise_for_status()
        return [SearchHit(row["doc_id"], row["score"]) for row in response.json()["items"]]


def variants_for_request(text, anchor):
    if "query_date" in signature(search_queries).parameters:
        return search_queries(text, query_date=anchor)
    return search_queries(text)


def noise(query):
    rng = random.Random("smartmail-russian-single-edit-v1:" + query.query_id)
    # Random word and one edit, seeded by query id. Pick alphabetic Cyrillic words
    # length >=5, using no relevance judgements, service dictionaries or predictions.
    tokens = list(re.finditer(r"(?<![\w-])[а-яёА-ЯЁ]{5,}(?![\w-])", query.query))
    token = rng.choice(tokens)
    word = token[0]
    choices = [(i, op) for i in range(1, len(word) - 1)
               for op in ("swap", "omit", "double") if op != "swap" or word[i] != word[i+1]]
    i, op = rng.choice(choices)
    value = {"swap": word[:i] + word[i:i+2][::-1] + word[i+2:],
             "omit": word[:i] + word[i+1:], "double": word[:i] + word[i:]}[op]
    return replace(query, query=query.query[:token.start()] + value + query.query[token.end():])


BOXES = {
    "fines": "box-12259a301ee2", "orders": "box-90560850fd8e", "cargo": "box-84bd433469cb",
}
# Probe topics, lexical diversity, phrase context and combined errors, fixed
# before running the candidate. The reference is a same-UI plain-word query.
PROBES = {
    "fines": {
        "штраф": ["штрафик", "штрфаик", "штрафиками"],
        "счёт": ["счётик", "счётиком", "счтеик"],
        "документ": ["документик", "документиками", "докмуент"],
        "письмо": ["письмецо", "письмецом"],
    }, "orders": {
        "заказ": ["заказик", "заказиков", "закзаик", "закааз", "заакз"],
        "доставка": ["доставочка", "доставочкой", "досатвка"],
        "товар": ["товарчик", "товарчиками", "твоар"],
        "мой заказ": ["мой заказик", "мой закзаик"],
        "скидка": ["скидочка", "скидочки"],
    }, "cargo": {
        "контейнер": ["контейнерчик", "контейнерчиках", "контейенр"],
        "отгрузка": ["отгрузочка", "отгрузочке", "отгрзука"],
        "груз": ["грузик", "грузиком"],
        "отчёт": ["отчётик", "отчётиком"],
    }
}
CONTROLS = ["график", "заказчик", "переводчик", "участник", "заявка", "сотрудник",
            "ключик@example.ru", "SKU-заказик-42", "от Ивана", "https://почта.рф/заказик"]

EXTRA_FORMS = {
    "fines": {"штраф": ["штрафик", "штрафиком", "штрафчиками", "штрафиках", "штрафчику", "штрфаик"]},
    "orders": {"срочный заказ": ["срочные заказы", "срочными заказиками"],
               "проверить документ": ["проверенные документы"]},
}

# Whether an entire primary variant matches intended lexical normalization.
# The inflectional and protective panels are reported separately. Spell changes
# and all generated query variants are saved so a fallback can be identified.
PHRASES = {
    "inflection": {
        "о возвратах": "о возврат", "срочными документами": "срочный документ",
        "проверяю документы": "проверять документ", "проверенные документы": "проверить документ",
        "упаковывают проверенные документы": "упаковывать проверить документ",
        "оформлялись срочные возвраты": "оформляться срочный возврат",
        "приходили с заказиками": "приходить с заказ",
        "по штрафчикам": "по штраф",
    },
    "protection": {
        "график": "график", "заказчик": "заказчик", "переводчик": "переводчик",
        "поводок": "поводок", "гвоздик": "гвоздик", "ручка": "ручка",
        "от Ивана": "от Ивана", "стали": "стали", "к двум": "к двум",
        "5 декабря 2028 года": "5 декабря 2028 года",
        "SKU-штрафик": "SKU-штрафик", "штрафик@example.com": "штрафик@example.com",
    },
}


def dump(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def main():
    archive, output = sys.argv[1:]
    output = Path(output)
    dataset = load_dataset(archive)
    dirty = replace(dataset, queries=tuple(noise(q) for q in dataset.queries))
    app = create_app(Settings(database_url="postgresql://unused", search_dataset=archive),
                     database_factory=lambda _: Mock(), store_factory=lambda _: Store(dataset))
    with TestClient(app) as client:
        client.get("/health/ready").raise_for_status()
        service = Transport(client)
        for kind, inputs in (("public", dataset), ("typo", dirty)):
            pred, _, errors = run_engine(inputs, service, 10)
            metrics, per_query = evaluate(inputs, pred, [1, 5, 10], errors=errors)
            run = dict(status="ok" if not errors else "failed", engine="event-aware BM25 via public API",
                       created_at=datetime.now(timezone.utc).isoformat(), code=code_version(),
                       engine_config={"config":"configs/search/bm25-event-aware.json",
                                      "correct_typos": True, "expand_word_forms": True, "request_limit": 10},
                       dataset=inputs.summary, query_set=kind)
            write_run(output/kind, run, metrics, per_query, pred)
            forms = []
            for orig, q in zip(dataset.queries, inputs.queries):
                corrected, _ = correct_query(q.query, preserve_forms=True)
                primary = variants_for_request(corrected, q.query_date)[0]
                forms.append({"query_id":q.query_id,"input":q.query,"original":orig.query,
                              "corrected":corrected,"primary":primary,
                              "receipt_preserved":receipt_day(corrected,q.query_date)[0] == receipt_day(primary,q.query_date)[0]})
            dump(output/kind/"wording.json", forms)
            print(kind, metrics["by_k"]["10"], "errors", len(errors), flush=True)
            if errors: raise ValueError(next(iter(errors.values())))
        sample = []
        for box, topics in PROBES.items():
            for reference, variants in topics.items():
                req = SearchRequest(reference, BOXES[box], date(2028,9,11))
                expected = [h.doc_id for h in service.search(req,10)]
                for variant in variants:
                    got = [h.doc_id for h in service.search(replace(req,query=variant),10)]
                    spelling, _ = correct_query(variant, preserve_forms=True)
                    sample.append(dict(box=box, reference=reference, variant=variant,
                                       spelling=spelling, primary=variants_for_request(spelling,req.query_date)[0],
                                       reference_count=len(expected), variant_count=len(got),
                                       same=bool(expected) and expected==got,
                                       overlap=len(set(expected)&set(got)), eligible=bool(expected)))
        controls = {}
        for word in CONTROLS:
            corrected, _ = correct_query(word, preserve_forms=True)
            controls[word] = {"spelling":corrected,"primary":search_queries(corrected)[0]}
        dump(output/"probes.json",sample)
        dump(output/"controls.json",controls)
        phrases = {}
        for kind, cases in PHRASES.items():
            phrases[kind] = {}
            for text, expected in cases.items():
                corrected, _ = correct_query(text, preserve_forms=True)
                variants = search_queries(corrected)
                phrases[kind][text] = dict(expected=expected,spelling=corrected,
                                            variants=variants,primary_match=expected == variants[0])
        dump(output/"phrases.json",phrases)
        extras = []
        for box,bases in EXTRA_FORMS.items():
            for base,surfaces in bases.items():
                req=SearchRequest(base,BOXES[box],date(2028,9,11))
                expected=[h.doc_id for h in service.search(req,10)]
                for surface in surfaces:
                    got=[h.doc_id for h in service.search(replace(req,query=surface),10)]
                    corrected,_=correct_query(surface,preserve_forms=True)
                    extras.append(dict(box=box,base=base,surface=surface,spelling=corrected,
                                       primary=variants_for_request(corrected,req.query_date)[0],nonempty=bool(expected),
                                       same=bool(expected) and got == expected))
        dump(output/"extra_forms.json",extras)
        print("Probe exact top10",sum(x["same"] for x in sample),
              "/",sum(x["eligible"] for x in sample),"(",len(sample),"attempted)")


if __name__ == "__main__":
    main()
