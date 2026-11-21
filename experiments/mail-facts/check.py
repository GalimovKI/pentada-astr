"""Prepare a fixed extraction diagnostic or score saved outputs; inference never sees labels."""
import argparse
from collections import defaultdict
from datetime import date, timedelta
import json
from pathlib import Path
from zipfile import ZipFile

# Manually reviewed references to the participant corpus. Each date is a (role, ISO day) fact.
REFERENCES = [
    ("L-0003d78e4a4a82d8fca8", None, [("event","2028-08-19")]),
    ("L-01b2be6356a86a83e0b7", None, []),
    ("L-2e15310247c7ebb3384f", None, [("event","2028-07-08")]),
    ("L-54d0f9b04f1fc670a928", "mail-93f13f7509@example.invalid", [("deadline","2027-11-21")]),
    ("L-b2352a2f299b49ea8595", "mail-b4b8c9c6b2@example.invalid", [("event","2028-10-02")]),
    ("L-f06f4b5598c0625aad2b", None, [("event","2028-08-19")]),
    ("L-072dd2bf78c5b41f2c07", "Милица Степановна Игнатьева", [("event","2028-08-23")]),
    ("L-0ebed84f8066e69fe541", "Лобанова Пелагея Аскольдовна", [("event","2028-08-23")]),
]
ANCHOR = "2028-09-19"
CASES = [
    ("letter","Тема: Сводка\nВчера завершили приёмку.\nС уважением, Вера Петрова","Вера Петрова",[("event","2028-09-18")]),
    ("letter","От: ivan@example.invalid\nКому: Леонид\nВстреча 20.09.2028. Ответ нужен до 21.09.2028.\nС уважением, отдел продаж","ivan@example.invalid",[("event","2028-09-20"),("deadline","2028-09-21")]),
    ("letter","Кому: Рита\nРита, высылаю материалы со встречи 16 сентября 2028 года.",None,[("event","2028-09-16")]),
    ("letter","От: Лев\nПересылаю.\n--- Пересланное сообщение ---\nОт: Диана\nС уважением, Диана","Лев",[]),
    ("letter","Здравствуйте! Денис просил передать смету Анне.",None,[]),
    ("query","Что вчера прислал Никита про встречу 15 сентября 2028 года?","Никита",[("receipt","2028-09-18"),("event","2028-09-15")]),
    ("query","Найди для Ирины письмо о вчерашней встрече.",None,[("event","2028-09-18")]),
    ("query","Письма от Тимофея про смету, полученные позавчера","Тимофея",[("receipt","2028-09-17")]),
    ("query","Покажи письмо про Алексея с дедлайном 22.09.2028",None,[("deadline","2028-09-22")]),
    ("query","Работа отчёт",None,[]),
    ("query","Письмо от marina@example.invalid насчёт билета на 2028-09-22","marina@example.invalid",[("event","2028-09-22")]),
]

# Additional examples frozen before the second inference run.
HOLDOUT = [
    ("letter","Олег, здравствуй! Завтра выступление на семинаре.\nС уважением, Жанна","Жанна",[("event","2028-09-20")]),
    ("letter","Для Алёны: акт от 18.09.2028 уже в архиве.",None,[("event","2028-09-18")]),
    ("letter","From: osip@example.invalid\nКому: Павел\nНапоминаю об оплате до 2028-09-25.","osip@example.invalid",[("deadline","2028-09-25")]),
    ("letter","Мы вчера получили ваше письмо. С уважением, Светлана","Светлана",[("event","2028-09-18")]),
    ("query","Что Зоя отправила сегодня насчёт завтрашней отгрузки?","Зоя",[("receipt","2028-09-19"),("event","2028-09-20")]),
    ("query","Ищу уведомление для Саввы о собрании 11.09.2028",None,[("event","2028-09-11")]),
    ("query","От Глеба было письмо позавчера?","Глеба",[("receipt","2028-09-17")]),
    ("query","Найди сообщение про Ивана без упоминания срока.",None,[]),
]



def cases(archive):
    with ZipFile(archive) as z:
        docs = {d["doc_id"]: d for d in map(json.loads, z.open("documents.jsonl"))}
        public = list(map(json.loads, z.open("queries_dev.jsonl")))
    for qid, sender, days in REFERENCES:
        d = docs[qid]
        yield dict(id=qid, kind="letter", text=d["doc"], doc_dt=d["doc_dt"]), ("corpus", sender, days)
    for i,(kind,text,sender,days) in enumerate(CASES):
        key = "doc_dt" if kind=="letter" else "query_date"
        yield {"id": f"case-{i}", "kind": kind, "text":text, key:ANCHOR}, ("example-"+kind,sender,days)
    for i,(kind,text,sender,days) in enumerate(HOLDOUT):
        key = "doc_dt" if kind=="letter" else "query_date"
        yield {"id": f"new-{i}", "kind":kind, "text":text, key:ANCHOR}, ("holdout-"+kind,sender,days)
    for q in public:
        expected_day = (date.fromisoformat(q["query_date"]) - timedelta(days=1)).isoformat()
        yield dict(id=q["query_id"],kind="query",text=q["query"],query_date=q["query_date"]), ("public",None,[("receipt",expected_day)])


def score(records, path):
    with path.open() as f:
        rows = [json.loads(line) for line in f]
    by_id = {r["id"]:r for r in rows}
    if len(rows)!=len(by_id) or by_id.keys()!={item["id"] for item,_ in records}:
        raise ValueError("Prediction coverage mismatch")
    metrics = defaultdict(lambda: dict(n=0, sender_exact=0, date_set_exact=0, both=0, invalid=0, rejected=0, errors=[]))
    for item,(part,sender,days) in records:
        row = by_id[item["id"]]
        m = metrics[part]
        m["n"] += 1
        m["rejected"] += row.get("rejected",0)
        if "error" in row:
            m["invalid"] += 1
            m["errors"].append(item["id"])
            continue
        pred_sender = row["sender"]["text"] if row["sender"] else None
        ok_sender = pred_sender == sender
        ok_dates = {(x["role"], x["iso"]) for x in row["dates"]} == set(days)
        m["sender_exact"] += ok_sender
        m["date_set_exact"] += ok_dates
        m["both"] += ok_sender and ok_dates
        if not (ok_sender and ok_dates):
            m["errors"].append(item["id"])
    return metrics


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action",choices=("prepare","score")); p.add_argument("archive",type=Path); p.add_argument("jsonl",type=Path)
    a=p.parse_args()
    samples=list(cases(a.archive))
    if a.action=="prepare":
        with a.jsonl.open("x") as out:
            for item,_ in samples:
                out.write(json.dumps(item,ensure_ascii=False)+"\n")
    else:
        print(json.dumps(score(samples,a.jsonl),ensure_ascii=False,indent=2))
