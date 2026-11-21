# Подготовка источников и запуск

Исходный корпус и замороженные запросы берутся из рабочего каталога. Адаптеры запускаются из корня репозитория. Тексты запросов, писем, индексы, веса и выдача по запросам в журнал не копируются.

```sh
r=reports/quality/runs/20261121T203640Z-a8bbe625
mkdir -p "$r/sources/e5" "$r/sources/soft" "$r/sources/hybrid"
git archive cedfd376aa32b88eb49f7b3654cc4b3c5822b20a experiments/mailsearch-e5 |
  tar -xf - -C "$r/sources/e5" --strip-components=2
git archive 33c38c4e8561faeeac973aa9f91a3248ada7742e experiments/soft-metadata |
  tar -xf - -C "$r/sources/soft" --strip-components=2
git archive c14c9c230cef321278796ecb9fe60711a9366513 \
  backend/src/mail_search/search/hybrid.py \
  backend/src/mail_search/search/hybrid_models.py \
  backend/src/mail_search/search/hybrid_index.py |
  tar -xf - -C "$r/sources/hybrid" --strip-components=4
python3 - "$r/sources/e5/mailsearch/query_expansion.py" <<'PY'
from pathlib import Path
import sys
file = Path(sys.argv[1])
text = file.read_text()
old = "tokenize=True, add_generation_prompt=True,"
assert text.count(old) == 1
file.write_text(text.replace(old, "tokenize=True, add_generation_prompt=True, return_dict=False,"))
PY
uv sync --project backend --locked --extra minilm
python3 infra/docker/fetch_minilm.py --output artifacts/models/minilm
python3 infra/docker/fetch_e5.py --output artifacts/models/e5
```

Исторические E5 и BM25 + E5 используют веса `intfloat/multilingual-e5-small` ревизии `614241f622f53c4eeff9890bdc4f31cfecc418b3`, файл `onnx/model.onnx` с SHA-256 `ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665` и `onnx/tokenizer.json` с SHA-256 `0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39`. Положите файлы в `artifacts/models/hybrid/e5`. Скопируйте штатные ARM64 веса MiniLM и токенизатор в `artifacts/models/hybrid/minilm`, сохранив ожидаемое имя графа `model_qint8_arm64.onnx`. Матрицу `artifacts/indexes/hybrid-e5-participants.npz` можно построить архивной командой из коммита `c14c9c2`; адаптер валидирует её веса и содержимое корпуса. Для Meta и RuBERT подготовьте в кеше `Qwen/Qwen2.5-0.5B-Instruct` ревизии `7ae557604adf67be50417f59c2c2f167def9a775` и `cointegrated/rubert-tiny2` ревизии `e8ed3b0c8bbf4fb6984c3de043bf7d2f4e5969ae`.

```sh
for stage in lexical minilm e5-old hybrid e5-dev minilm-full; do
  uv run --project backend --locked --extra minilm python "$r/eval_suite.py" "$stage"
done
for stage in rubert roles; do
  uv run --project backend --locked --extra minilm \
    --with 'transformers==4.57.3' --with 'torch==2.10.0' \
    python "$r/eval_variants.py" "$stage"
done
uv run --project backend --locked --extra minilm python "$r/eval_variants.py" enron
uv run --project backend --locked --extra minilm \
  --with 'mlx-lm==0.29.1' --with 'transformers==4.57.3' \
  python "$r/eval_variants.py" doc2query
uv run --project backend --locked --extra minilm python "$r/eval_variants.py" doc-rerank
python3 reports/quality/runs/query-intent-analysis/build_baselines.py
uv run --project backend --locked --extra minilm python "$r/verify_scores.py" \
  reports/quality/query-intent-analysis.html data/benchmarks/team-holdout-v1/eval "$r"
```

Генерация фраз для 6419 кандидатов обрабатывает только текст письма. Архивный скрипт фиксирует Qwen в MLX, промпт, пределы токенов и сохраняет векторы в локальном SQLite. Указанные изменения загрузчика токенизатора сохраняют тот же токенизированный запрос.
