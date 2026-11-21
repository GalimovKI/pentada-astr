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

## First CI deployment after publication

Run 44951289621 (e5355d1): backend and both frontend test jobs succeeded.
Deploy started 2026-11-21T21:24:29Z; at 21:46 UTC it was still downloading GPU
dependencies into the new server cache mount. E5 fetch took 8.5s; model fetch
processes had exited. uv is making progress: 7,455,739 bytes written over 12s.
A subsequent 6.06s sample of its TCP connection received 2,284,408 bytes
(368.2 KiB/s). This is a cold cache fill on the academic host; the local cache
was not transferred there. Job timeout is 40 minutes; completion is not yet
confirmed. The 8.37s result above applies only to the local warm rebuild.

Deployed dev remains d2ca7bd; main/dev backend and DB containers healthy, API
readiness ready, public /dev/ and /dev/api/v1/mailboxes HTTP200. /home has
92GiB available, memory available 120GiB. No job cancellation/restart or server
configuration/code changes were made during this read-only investigation.
Source: https://github.com/GalimovKI/pentada-astr/actions/runs/44951289621
