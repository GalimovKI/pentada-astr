# MiniLM на GPU учебного хоста

GPU используется только для нейросетевого reranking MiniLM. BM25, HTTP и PostgreSQL
работают на CPU. В `/dev/` выберите «BM25 по дате + MiniLM (75/25)».
Основной BM25 в `/main/` не требует GPU. Правила отбора кандидатов, RRF 75/25,
глубина 20 и токенизация не меняются.

CPU по умолчанию использует прежний INT8-граф. CUDA использует FP32 ONNX той же
MiniLM, той же закреплённой ревизии; SHA-256 проверяется при загрузке.
Выдача может отличаться от квантованной версии, поэтому перед переключением нужен
общий eval. TF32 выключен. CUDA-сборка использует отдельный extra `minilm-gpu`,
ONNX Runtime 1.23.x, библиотеки CUDA 12 и cuDNN из lock-файла. CPU extra `minilm`
и GPU extra взаимоисключающие; установка обоих пакетов ONNX в одну среду запрещена.
GPU-сборка рассчитана на Linux x86_64.

## Docker Compose

Нужны Docker с CDI и установленный администратором NVIDIA Container Toolkit.
На текущем учебном хосте rootless Docker уже видит `/var/run/cdi/nvidia.yaml`.
Проверить UUID и доступные устройства:

```bash
nvidia-smi --query-gpu=index,uuid,memory.free,utilization.gpu --format=csv
nvidia-ctk cdi list
```

Выберите одну разрешённую карту (UUID устойчивее номера). Не используйте `all`.
Для ручного запуска на учебном хосте, из корня исходников:

```bash
export GPU_CDI_DEVICE=nvidia.com/gpu=GPU-ЗАМЕНИТЕ-НА-UUID
export APP_IMAGE_TAG=dev-gpu-local
# Тот же env, project и пути к данным, что у действующего dev:
docker --context rootless compose --env-file ~/pentada-astr-dev/shared/.env.production \
  -p pentada-mailsearch-dev -f compose.production.yaml -f compose.origin.yaml \
  -f compose.dev-evaluations.yaml -f compose.gpu.yaml up -d --build backend
```

Не запускайте эту команду поверх рабочего dev до проверки отдельного образа.
Сначала соберите его, запустите проверку CUDA и eval. Внутри контейнера выбранная
карта имеет индекс 0, независимо от её индекса на хосте.

```bash
docker --context rootless run --rm --network none \
  --device "$GPU_CDI_DEVICE" \
  -v "$PWD/scripts/check_minilm_gpu.py:/tmp/check_minilm_gpu.py:ro" \
  pentada-mailsearch-backend:dev-gpu-local python /tmp/check_minilm_gpu.py
```

Проверка требует CUDA MatMul/Attention/Gemm в профиле реального inference.
Одного `nvidia-smi` или списка providers для подтверждения недостаточно.
При отсутствии CUDA EP или ошибке его инициализации код завершает загрузку MiniLM
с ошибкой, вместо незаметного перехода всей сессии на CPU. Некоторые служебные
операции графа могут выполняться на CPU.

`MINILM_GPU_MEMORY_MB=2048` ограничивает арену памяти **каждой** ONNX-сессии,
а не весь процесс: CUDA-контекст и библиотеки требуют дополнительной памяти.
Выбор разных корпусов и запуск eval создают отдельные сессии. Следите за
`nvidia-smi`, не запускайте несколько backend workers и не занимайте все карты.

## Существующий CI/CD и откат

На учебном хосте в `~/pentada-astr-dev/shared/gpu-device` запишите одну строку
`nvidia.com/gpu=GPU-…`. Установите актуальный `infra/ci/origin` как
`~/pentada-astr-dev/origin` с правами 755. `infra/ci/deploy.py` и wrapper добавят
GPU overlay последним только для этого окружения. `/main/` останется на CPU,
пока аналогичный файл не появится в его собственном каталоге.

GPU-код должен быть в ветке, которую разворачивает CI. До слияния этой ветки
следующий deploy старого `dev` вернёт CPU-образ. Автоматический откат на старый
релиз без `compose.gpu.yaml` также использует CPU. Образы имеют прежние теги
`environment-SHA`: не переключайте CPU/GPU режим одного SHA с `--no-build`;
соберите целевой образ заново.

Для возврата к CPU уберите `shared/gpu-device`, пересоберите и пересоздайте backend
обычным wrapper. Базы, фронтенд и SSH-туннель менять не требуется. Для немедленного
отката переключите `current` на сохранённый CPU-релиз и выполните
`origin up -d --no-build --wait backend`.

`gpu-run` из примера пользователя в аккаунте `rusikye` не найден. Он не нужен
для подтверждённого прямого доступа CDI; не подменяйте им Compose, не проверив
доступ к сети PostgreSQL, томам и перезапуску контейнера.

Источники: [ONNX Runtime CUDA EP](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html),
[NVIDIA CDI](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/cdi-support.html).
