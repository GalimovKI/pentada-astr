"""Small counterfactual mailbox. Labels describe independently generated envelope fields."""
from itertools import product


def contrast_set():
    names = ("Анна", "Тимофей", "Борис")
    days = ("2028-09-16", "2028-09-17", "2028-09-18")
    docs, facts = [], {}
    for sender, recipient, day, event, subject in product(
        names, names, days, ("2028-09-15", "2028-09-17"), ("смета", "договор")
    ):
        if sender == recipient:
            continue
        mentioned = next(n for n in names if n not in (sender, recipient))
        did = f"doc-{len(docs):03}"
        text = (f"От: {sender}\nКому: {recipient}\nТема: {subject}\nТекст письма:\n"
                f"Обсуждали документ «{subject}» на встрече {event}. На встрече выступил(а) {mentioned}.")
        docs.append(dict(doc_id=did, synthetic_user="diag", doc_dt=day, doc=text))
        facts[did] = dict(sender=sender, recipient=recipient, mentioned=mentioned,
                          receipt=day, event=event, subject=subject)
    cases = [
        ("Что Анна прислала вчера про договор?", dict(sender="Анна", receipt=days[1], subject="договор")),
        ("Вчерашние письма для Анны про договор", dict(recipient="Анна", receipt=days[1], subject="договор")),
        ("Кто выступил на встрече? Письмо про смету, где упомянут Тимофей", dict(mentioned="Тимофей", subject="смета")),
        ("Найди письмо от Тимофея про смету со встречи 2028-09-15", dict(sender="Тимофей", event="2028-09-15", subject="смета")),
        ("Что отправили Тимофею вчера про смету?", dict(recipient="Тимофей", receipt=days[1], subject="смета")),
        ("Письма от Анны для Бориса про договор", dict(sender="Анна", recipient="Борис", subject="договор")),
        ("Письма от Бориса для Анны про договор", dict(sender="Борис", recipient="Анна", subject="договор")),
        ("Смета со вчерашней встречи, которую прислал Борис", dict(sender="Борис", event=days[1], subject="смета")),
        ("Вчерашняя почта от Бориса про смету", dict(sender="Борис", receipt=days[1], subject="смета")),
        ("Письма про договор, полученные 2028-09-16, о встрече 2028-09-15", dict(receipt=days[0], event="2028-09-15", subject="договор")),
        ("Договор со встречи 2028-09-17 в письме от 2028-09-18", dict(receipt=days[2], event=days[1], subject="договор")),
        ("Смета от Анны для Тимофея, полученная вчера", dict(sender="Анна", recipient="Тимофей", receipt=days[1], subject="смета")),
        ("Что писал Тимофей про договор?", dict(sender="Тимофей", subject="договор")),
        ("Письма Борису о смете", dict(recipient="Борис", subject="смета")),
        ("Письма про договор со встречи 2028-09-15", dict(event="2028-09-15", subject="договор")),
        ("Найди письмо про смету", dict(subject="смета")),
    ]
    queries, qrels, intents = [], {}, {}
    for i, (text, gold) in enumerate(cases):
        qid = f"diag-{i:02}"
        queries.append(dict(query_id=qid, query=text, query_date=days[2], synthetic_user="diag"))
        qrels[qid] = {did: 1 for did, fields in facts.items() if all(fields[k] == v for k, v in gold.items())}
        intents[qid] = gold
    return docs, queries, qrels, intents
