# Независимый кеш Docker backend

Локальный коммит e5355d122b8704964f4ebbf4010854502fd6288c, ветка codex/docker-build-cache, основа dev d2ca7bd.
После проверок пользователь разрешил перенос изменений в свежий dev и push.
Коммит опубликован в dev; эта запись публикуется отдельно в team-memory.
Во время проверок исходники были локальными; Dockerfile после проверок не менялся.

Причина исходной проблемы: backend/src копировался до uv sync --no-cache,
загрузка моделей выполнялась после копирования установленного приложения.
Предыдущая диагностика: локальная запись20261121T210556Z-60b233e4.

Теперь dependencies использует uv sync --locked --no-install-project и
BuildKit cache mount отдельно для архитектур, UV_LINK_MODE=copy, timeout120s.
MiniLM/E5 скачиваются в независимых стадиях только по скриптам/платформе/аргументам.
Приложение собирается в wheel и устанавливается отдельным runtime-слоем
с --network=none, --offline, --no-deps. Зависимости и модели остаются в стабильных
слоях образа при изменениях кода. Версии пакетов и модельные SHA не изменялись.

Проверки на локальном Docker29.8.2/OrbStack(macOSARM64): CPUarm64 и MiniLMCUDA+
E5CPUamd64(эмуляция), warm rebuild после изменения __init__.py в отдельном
контексте; RUN dependencies/minilm-model/e5-model=CACHED. Маркер нового исходника
проверен в установленном пакете. Общие первые9filesystemlayers GPUобразов.
GPUrebuild8.367s, экспорт0.7s (один замер с прогретым кешем, не serverdeploy).
Полностью отключённая сеть CPUrebuild успешна. GPUmodelSHA256совпадают с pinned.
79backendtestsGPUimage+PostgreSQL17.12 без пропусков; CPU79tests с3skipE5безNumPy.
11infratests, mailsearchvalidate успешны. uv/wheel отсутствуют в runtime.

Команды и границы кеша в infra/docker/BUILD_CACHE.md этого коммита.
GPUинференс/eval не повторялись: изменена только упаковка. Серверы не тронуты.
Кеш требует постоянного builder; первая новая сборка/очистка/новые версии требуют
загрузок. Типичные правки исходников больше не требуют загрузки CUDA/моделей.
