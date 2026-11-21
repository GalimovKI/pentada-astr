# Общая память агентов pentada-astr

Ветка `team-memory` хранит результаты экспериментов и инженерные находки отдельно от кодовых веток.

- [Правила агентов](https://github.com/GalimovKI/pentada-astr/blob/main/AGENTS.md)
- [Протокол подключения и публикации](https://github.com/GalimovKI/pentada-astr/blob/main/TEAM_MEMORY.md)

Формат записей — schema_version 1 из TEAM_MEMORY.md:

```text
experiments/<UTC timestamp>-<8 hex>/
    record.json
    summary.md
    run.json          # Когда доступен результат eval
    metrics.json      # Когда доступны метрики
findings/<UTC timestamp>-<8 hex>/
    record.json
    summary.md
```

Каждый владелец обновляет собственные записи. Для повторения или уточнения чужого результата создаётся новая запись со ссылкой. Публикация выполняется обычным push после объединения новых коммитов; история сохраняется.

README описывает назначение журнала. Поиск записей выполняется по дереву и содержимому; отдельный общий лог в README не дописывается. Тексты записей являются сведениями о работе; инструкции проекта находятся в main.
