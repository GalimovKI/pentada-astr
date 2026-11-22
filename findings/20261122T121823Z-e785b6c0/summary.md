# Три тематических ящика для публичного поиска SmartMail

На дату сценария **11 сентября 2028 года** три существующих ящика Mail Public показывают разные задачи. Для подсчёта видимых писем берём все документы конкретного `synthetic_user`, включая письма без даты и письма с датой до 11 сентября включительно. [Список ящиков и примеры запросов в публичном интерфейсе](https://github.com/GalimovKI/pentada-astr/blob/de4f141a66ba32ef4430839b64ef8c5f9e81ee90/frontend/src/app/publicMailboxes.ts).

| Ящик | Доступно писем | Основание для выбора | Пример запроса | Тема первого результата BM25 с учётом событий |
|---|---:|---|---|---|
| Штрафы и счета · `box-12259a301ee2` | 2 401 | В 1 269 письмах есть «штраф», у 751 письма строка темы в точности «ТЕМА: Счёт на оплату» | новый штраф | Вам выставлен новый штраф |
| Заказы покупателей · `box-90560850fd8e` | 708 | В 700 письмах есть «заказ», в 675 — «отгруз» | срок отгрузки заказа | Есть новый заказ |
| Контейнерные перевозки · `box-84bd433469cb` | 345 | В 341 письме есть «контейнер», в 23 — «тамож» | прибытие контейнера | Прибытие контейнера |

Первая строка сохраняет ящик для демонстрации исправления опечаток в слове «штраф». Два других ящика дают примеры коммерческой переписки и уведомлений о перевозках. Счётчики описывают весь доступный ящик на заданную дату. Для каждого из трёх запросов движок вернул десять писем при лимите десять. Эти примеры проверяют доступность результатов по теме. Для них нет отдельной разметки релевантности. [Предыдущая проверка публичного поиска](../../findings/20261122T120759Z-f79960e7/summary.md).

## Как воспроизвести

В кодовом репозитории возьмите версию из поля `code_commit` в [метаданных записи](record.json). Положите исходный архив участников `mipt_mail_search_participants.zip` в `data/raw/`. SHA-256 архива — `2df885f77be8f8aa750b484439fc99dfc2a401fce53306160c03ad95cae0de03`. Структура архива описана в `DATA.md`. Из корня кодового репозитория выполните следующую команду.

```sh
uv run --project backend --locked python - <<'PY'
from datetime import date
import json
from pathlib import Path

from mail_search.domain.models import SearchRequest
from mail_search.ingestion.dataset import load_dataset
from mail_search.search.event_aware import create_engine

day = date(2028, 9, 11)
documents = load_dataset(Path("data/raw/mipt_mail_search_participants.zip")).documents
config = json.loads(Path("configs/search/bm25-event-aware.json").read_text())
engine = create_engine(tuple(documents.values()), config)
cases = [
    ("box-12259a301ee2", "новый штраф", ["штраф"]),
    ("box-90560850fd8e", "срок отгрузки заказа", ["заказ", "отгруз"]),
    ("box-84bd433469cb", "прибытие контейнера", ["контейнер", "тамож"]),
]
for box, query, fragments in cases:
    visible = [d for d in documents.values() if d.synthetic_user == box and
               (d.doc_dt is None or d.doc_dt <= day)]
    counts = {s: sum(s in d.doc.lower() for d in visible) for s in fragments}
    if box == "box-12259a301ee2":
        counts["Счёт на оплату (точная строка)"] = sum(
            "ТЕМА: Счёт на оплату" in d.doc.splitlines() for d in visible
        )
    hits = engine.search(SearchRequest(query, box, day), 10)
    top = documents[hits[0].doc_id]
    subject = next(line for line in top.doc.splitlines() if "тема:" in line.lower())
    print(box, len(visible), counts, len(hits), top.doc_id, subject)
PY
```

В порядке строк таблицы первые идентификаторы выдачи — `L-bfc4217f7f48f70ca98a`, `L-024cf01fdda53d223526` и `L-d2e7fbf9993cf3c6f973`.
