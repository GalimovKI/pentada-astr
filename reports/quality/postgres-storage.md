# Проверка PostgreSQL-хранилища, 21 ноября 2026

Ветка `feature/wendigo`, основа `d8912d2f4170bf107a95e227c54a8d3f688f5b2a`.
Проверки выполнены на незакоммиченном рабочем дереве этой задачи.
PostgreSQL 17.12 (Docker, named volume), Python 3.15.2, SQLAlchemy 2.1.9,
Psycopg 3.3.9, Alembic 1.20.1; зависимости закреплены в `backend/uv.lock`.
В окружении `uv` установлен через `python3 -m pip install --user uv`, поэтому
команды запускались как `python3 -m uv …` (эквивалент `uv …` из README).

## Выполненные команды

```bash
python3 -m uv sync --project backend
python3 -m uv run --project backend --locked python -m unittest discover -s backend/tests -t backend -v
docker compose up -d --wait
python3 -m uv run --project backend --locked --env-file .env alembic -c backend/alembic.ini upgrade head
python3 -m uv run --project backend --locked --env-file .env python -m unittest discover -s backend/tests -t backend -v
python3 -m uv run --project backend --locked mailsearch validate
python3 -m uv run --project backend --locked --env-file .env mailsearch import-postgres
docker compose restart db
docker compose up -d --wait
python3 -m uv run --project backend --locked --env-file .env mailsearch import-postgres
docker compose stop db
python3 -m uv run --project backend --locked mailsearch run --output reports/quality/runs/postgres-offline-check
docker compose up -d --wait
python3 -m uv run --project backend --locked --env-file .env alembic -c backend/alembic.ini check
git diff --check
```

## Результат

- Без конфигурации БД: 21 прежний тест пройден, 8 новых PostgreSQL-тестов явно пропущены.
- С `TEST_DATABASE_ADMIN_URL`: все 29 тестов пройдены. Каждый тест БД создаёт и удаляет только собственную `mailsearch_test_<uuid>`.
- Проверены миграция пустой БД, совпадение схемы с metadata, пакетный и конкурентный импорт, повторный запуск, откат после записанного первого пакета, конфликт наборов, ограничения схемы, текст/ID/NULL без потерь, изоляция и фильтрация дат, пагинация, порядок выдачи, отсутствие N+1, неизвестные ящики и отсутствующие письма.
- Реальный импорт: 16 376 писем, 12 ящиков, 433 NULL-даты. Повторный запуск возвращает `already_imported`.
- Fingerprint загрузчика и БД: `0daa664136d798c1ed2fe50802a7d236f93b4891d56f2353bc5b807b56601665`.
- Дополнительный локальный Python-скрипт сравнил все `Document` из БД с `load_dataset`, затем обошёл каждый ящик страницами по 137 писем и сверил полноту и отсутствие повторов. Проверка выполнена до и после перезапуска, все поля совпали.
- При остановленном контейнере и без DATABASE_URL BM25 обработал 99 запросов, ошибок 0. Recall@10 = 0.444141, nDCG@10 = 0.409748 — значения исходного бейзлайна. Это проверка регрессии, не новый эксперимент поиска.

## Ограничения

Удалённый сервер, TLS с реальным CA и восстановление дампа на другом сервере
не проверялись. Инструкции переноса приведены в README. HTTP API, frontend,
векторные индексы и серверная нагрузка в эту задачу не входят.
Код и запись командного журнала не отправлялись: push исключён пользовательским
запросом. Локальный `.env` с новым случайным паролем и данные volume сохранены,
контейнер оставлен запущенным. Секреты и корпус не включены в Git.

## Объединение со свежим main

После `daa8c4f` объединён `main` на `48a2ea3` (Snowball и команда одиночного
поиска). Конфликты в CLI, зависимостях, README и COMPONENTS разрешены с
сохранением обоих решений; lock-файл пересобран через `uv lock` без обновления
существующих версий. Теперь доступны и `search`, и `import-postgres`.

Проверки объединённого рабочего дерева перед merge-коммитом:

- `python3 -m uv sync --project backend --locked` — успешно.
- Полный unittest с `--env-file .env` — **34 теста пройдены**, включая 8 PostgreSQL-тестов.
- `mailsearch validate` — manifest и fingerprint прежние.
- `mailsearch import-postgres` — `already_imported`, 16 376 писем / 12 ящиков / 433 NULL-даты.
- `mailsearch run --config configs/search/bm25-stemmed.json --output reports/quality/runs/wendigo-main-merge-stemmed` — 99 запросов, 0 ошибок.
- Весь `metrics.json` совпал с записью `experiments/20261121T120349Z-10730634` из `origin/team-memory`: Recall@10 = 0.861505, nDCG@10 = 0.891021.

Это проверка совместимости при merge, а не изменение поискового алгоритма.
Отдельная запись командного журнала не публиковалась; push не выполнялся.
