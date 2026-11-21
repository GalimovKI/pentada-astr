# Проверка переноса инфраструктуры на main, 21 ноября 2026

Основа: `origin/main` — `9b0b8013729f29c7a86abf38e48f921a6328a290`.
Ветка: `feature/wendigo`. Перенесены Dockerfile, production/edge/origin Compose,
Caddy, подготовка БД, SSH unit и документация из `6376379`.
Код backend, поисковые конфигурации и модель совпадают с указанным main.
В новых Docker-настройках сохранён его default: `load_event_aware` и
`configs/search/bm25-event-aware.json`.

Проверки выполнены локально на macOS, Docker Engine 29.8.2, Compose 5.5.0,
в отдельном проекте `pentada-wendigo-check`. Временный env содержит отдельный
пароль; корпус подключён read-only. Для интеграционных тестов только тестовая
БД дополнительно опубликована на `127.0.0.1:55441`; этого override нет в Git.
Web проверялся на `http://127.0.0.1:18090`.

Результаты:

- `uv sync --project backend --locked` и `mailsearch validate` прошли.
- Production, edge и origin Compose прошли `config --quiet`.
- `docker compose ... build` собрал backend и frontend; frontend build включает
  TypeScript-проверку. Неизменённые слои frontend переиспользованы из кеша.
- `run --rm prepare`: 12 ящиков, 16 376 писем, 433 неизвестные даты,
  fingerprint `0daa664136d798c1ed2fe50802a7d236f93b4891d56f2353bc5b807b56601665`.
- `up -d --wait --wait-timeout 300`: db/backend/web healthy.
- `python -m unittest discover -s backend/tests -t backend -v` с
  `TEST_DATABASE_ADMIN_URL` отдельной БД: **62 теста, OK, без пропусков**.
- `python3 scripts/check_production.py --url http://127.0.0.1:18090`:
  5 статических ресурсов, 12 ящиков, HTTP-методы, ошибки и headers корректны.
- `uv run --project backend --locked python scripts/check_http_api.py
  --url http://127.0.0.1:18090`: **99 поисков совпали с offline**, 99 писем
  открыты, проверены 2401 письмо и 13 страниц пагинации.
- `caddy validate` с `API_UPSTREAM=127.0.0.1:18081` прошёл.

После проверки локальные контейнеры остановлены; тестовый volume сохранён.
Действующие VPS и учебный хост в этой задаче не обновлялись. Браузерные тесты,
новый публичный деплой, HTTPS, нагрузочный p99 и eval качества не выполнялись.
Поиск относительно main не менялся; HTTP regression проверяет упаковку и API.
Проверки выполнены перед локальным коммитом. По просьбе пользователя push
не выполнялся, новая запись в `team-memory` не публиковалась.
