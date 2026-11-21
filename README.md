Kirill лучший

## Умный поиск в Почте

- [Требования и описание проекта](PROJECT.md)
- [Компоненты продукта](COMPONENTS.md)
- [Предоставленные данные](DATA.md)
- [Запуск eval и подключение поискового движка](EVAL.md)
- [Результат первого BM25-бейзлайна](reports/baseline.md)

Для локального eval нужен Python 3.11 или новее; внешних зависимостей нет.

После размещения архива участников в `data/raw/mipt_mail_search_participants.zip`:

```bash
python3 -m unittest discover -s tests -v
python3 -m mailsearch validate
python3 -m mailsearch run --output runs/my-first-run
```
