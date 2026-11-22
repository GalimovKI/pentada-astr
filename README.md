<h1 align="center"><img src="docs/assets/smartmail-logo.svg" width="310" alt="SmartMail"></h1>

<p align="center"><strong>Найдите письмо, даже если помните только его смысл.</strong><br>
Умный поиск в Почте · кейс VK Tech на хакатоне МФТИ.</p>

<p align="center"><a href="https://smartmail-hackaton.ru/main/"><strong>Открыть сайт · smartmail-hackaton.ru/main/ ↗</strong></a></p>

## Рекомендуемая модель

**Для поиска писем используйте «BM25 с учётом событий» (`bm25-event-aware`).** Этот движок включён по умолчанию в основной версии SmartMail и работает на CPU. Среди девяти движков из сравнения ниже он показал лучший **nDCG@10 — 0,9976** на 99 публичных запросах Mail Public. [Конфигурация](configs/search/bm25-event-aware.json) · [Команда запуска](EVAL.md#9-основной-метод-поиска) · [Метрики прогона](https://github.com/GalimovKI/pentada-astr/blob/team-memory/experiments/20261122T123953Z-6968d61e/candidate/public/metrics.json)

<p align="center"><a href="https://smartmail-hackaton.ru/main/"><img src="docs/assets/search-demo.gif" width="880" alt="Поиск в SmartMail: выбор ящика «Заказы покупателей», исправление «закзаик» на «заказик» и открытие найденного письма"></a></p>

## Качество поиска

Результаты движков из dev на корпусе Mail Public из 16 376 писем.

| Движок | Recall@10 | nDCG@10 | MRR@10 |
|---|---:|---:|---:|
| **BM25 с учётом событий** | **0,9376** | **0,9976** | **1,0000** |
| BM25 + E5 · объединение рангов (RRF) | 0,9366 | 0,9949 | 1,0000 |
| E5 → BM25 | 0,9342 | 0,9935 | 0,9949 |
| BM25 по дате + MiniLM (75/25, ARM64 INT8) | 0,9366 | 0,9931 | 0,9949 |
| BM25 с весами запроса | 0,8648 | 0,9173 | 0,9848 |
| BM25 со стеммингом | 0,8615 | 0,8910 | 0,9444 |
| BM25 → E5 | 0,8547 | 0,8895 | 0,9163 |
| BM25 базовый | 0,4441 | 0,4097 | 0,4590 |
| E5 · косинусная близость (INT8) | 0,2961 | 0,2004 | 0,2245 |

<details>
<summary>Скорость E5 и MiniLM на CPU и GPU</summary>

Задержка dev API в миллисекундах. 99 последовательных запросов, до 100 писем, без отдельного прогрева. CPU — Intel Xeon Gold 6338, GPU — NVIDIA A100 80 GB PCIe.

| Движок | CPU p50 | CPU p99 | GPU p50 | GPU p99 |
|---|---:|---:|---:|---:|
| E5 · косинусная близость | 29,72 | 184,76 | 16,77 | 109,04 |
| BM25 по дате + MiniLM | 816,34 | 2 422,42 | 43,24 | 685,47 |

</details>

[Методика оценки](EVAL.md) · [Сравнение на EnronQA](https://github.com/GalimovKI/pentada-astr/blob/e3781b900d3badfc0fe94c13f7336962c3633433/reports/quality/e5-hybrids.md) · [Запуск](DEPLOYMENT.md) · [Архитектура](COMPONENTS.md)

## Мультфильм «Поиск и двадцать сантиметров»

https://github.com/user-attachments/assets/1194513c-0adf-4dbd-91b2-e1e700cac703

[Скачать мультфильм в MP4 · 1 мин 44 с](https://github.com/GalimovKI/pentada-astr/raw/refs/heads/main/docs/assets/hackfpmi3012-search-cartoon-v3.mp4)
