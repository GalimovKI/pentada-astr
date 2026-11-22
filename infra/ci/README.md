# CI/CD: независимые `/main/` и `/dev/`

| | main | dev |
|---|---|---|
| Ветка | `main` | `dev` |
| Адрес | `http://176.12.68.100/main/` | `https://smartmail-hackaton.ru/dev/` |
| Учебный каталог | `~/pentada-astr` | `~/pentada-astr-dev` |
| Compose backend/БД | `pentada-mailsearch` | `pentada-mailsearch-dev` |
| Origin API (loopback) | 28081 | 28091 |
| Туннель на VPS (loopback) | 18081 | 18091 |
| Frontend на VPS (loopback) | 18080 | 18090 |
| Frontend health (loopback) | 18082 | 18092 |
| Compose frontend | `pentada-edge-main` | `pentada-edge-dev` |

Корневой `/` перенаправляется на `/main/`, `/main` и `/dev` — на адреса с завершающим
слешем. Общий Caddy gateway (`pentada-gateway`, порты 80 и 443) сохраняет префикс при
проксировании. Caddy каждого frontend снимает только свой префикс перед чтением
статики и обращением к backend. Frontend собирается с Vite base `/main/` или `/dev/`;
его API, JS, favicon и шрифты остаются внутри соответствующего пути.

Всего работают семь контейнеров: gateway и два frontend на VPS, два backend и два
PostgreSQL на учебном хосте. БД имеют отдельные volumes, роли и пароли. Корпус может
быть общим read-only файлом. Конфигурация поиска каждого окружения задаётся его env;
алгоритмы поиска этот change не меняет. Нагрузка на железо и gateway остаются общими.

## Ветки и проверки

[Workflow](../../.github/workflows/ci-cd.yml) запускает проверки для PR в `main`/`dev`
и push в обе ветки. Backend проверяется с отдельным тестовым PostgreSQL. Frontend
проходит unit tests, TypeScript/Vite build и браузерные сценарии на desktop/mobile
для **обоих** префиксов. Fixture-тестам не нужен настоящий корпус.

После успешных проверок push в `dev` обновляет только dev, push/merge в `main` —
только main. Есть `Run workflow` для обеих веток. Прямой push также запускает деплой;
обязательный MR обеспечивается настройками branch protection, не этим YAML.
Устаревший SHA пропускается, если ветка уже продвинулась. Начатый deploy не отменяется
новым push. Один runner выполняет задания последовательно; файлы блокировок также
исключают конкурирующее изменение одного окружения и одновременную сборку на VPS.

Ветки первоначально созданы от одного свежего main. Дальше в dev проверяются изменения,
затем MR `dev → main` переносит проверенную версию в рабочее окружение. Миграция
инфраструктуры установлена на обоих хостах вручную; для автоматизации новые workflow
и скрипты должны попасть в **обе** ветки. До этого старый workflow main не совместим
с новым протоколом receiver и остановится до изменения контейнеров.

## Что делает deploy

1. Архивирует точный коммит в `releases/<SHA>`, без checkout `.env`, корпуса и ключей.
2. Проверяет миграции. Если они изменились относительно активного релиза, останавливается
   до сборки и переключения: нужен отдельный план ручного обновления этого окружения.
3. Собирает backend на учебном хосте, frontend на VPS. Теги содержат окружение и SHA.
   [Кеш backend](../docker/BUILD_CACHE.md) сохраняет зависимости и модели отдельно
   от исходников приложения.
4. Сохраняет закрытый backup env и `pg_dump` существующей БД. Для первой установки
   ещё нет БД для backup; этот случай явно отражён в `previous.json`.
5. Запускает БД, prepare (миграции/импорт), backend и ждёт readiness.
6. Обновляет только выбранный frontend, проверяет его локальный URL с префиксом,
   затем публичный URL через gateway. После успеха переключает `current`.

При ошибке скрипт пытается вернуть предыдущий код **того же окружения**. Второе
окружение не переключается. БД автоматически не восстанавливается; при ошибке
самого отката job остаётся failed, требуется ручное восстановление. Возможен короткий
перерыв API на время пересоздания backend: zero downtime здесь не обеспечивается.

## Файлы и секреты

- Runner: `~/actions-runner-pentada`, unit `pentada-actions-runner.service`.
- Repo runner `pentada-academic`, label `pentada-production` используется для обоих
  окружений (имя label сохранено для совместимости регистрации).
- Настройки: `~/.config/pentada-ci.json`, права 600, без паролей.
- Env БД: `<origin_root>/shared/.env.production`, права 600, parent 700.
- Deploy key: `~/.ssh/pentada-deploy`, права 600; SSH config
  `~/.ssh/pentada-deploy-config`, проверенный `~/.ssh/pentada-edge-known_hosts`.
- Main tunnel key/unit: `~/.ssh/pentada-edge`, `pentada-edge-tunnel.service`.
- Dev tunnel key/unit: `~/.ssh/pentada-edge-dev`, `pentada-dev-tunnel.service`.
- VPS receiver: `/usr/local/sbin/pentada-edge-receive`, root-owned.
- VPS releases: `/opt/pentada/environments/{main,dev}/releases/<SHA>` и отдельные `current`.
- Gateway: `/opt/pentada/gateway-source/compose.gateway.yaml` и
  `infra/docker/Gateway.Caddyfile` внутри этого каталога. Обычный deploy их не меняет.

```json
{
  "docker": "~/.local/lib/pentada-docker/bin/docker",
  "ssh_config": "~/.ssh/pentada-deploy-config",
  "environments": {
    "main": {
      "origin_root": "~/pentada-astr",
      "origin_project": "pentada-mailsearch",
      "public_url": "http://176.12.68.100/main"
    },
    "dev": {
      "origin_root": "~/pentada-astr-dev",
      "origin_project": "pentada-mailsearch-dev",
      "public_url": "http://176.12.68.100/dev"
    }
  }
}
```

## Первичная установка и переход с одного окружения

Базовая установка Docker, rootless Docker, корпуса и main-туннеля описана в
[DEPLOYMENT.md](../../DEPLOYMENT.md). Старый трёхконтейнерный запуск из этого документа
не запускайте поверх работающего gateway: он занимает порт 80 и использует старые пути.

1. На учебном хосте создайте `~/pentada-astr-dev/{releases,shared,backups}`. Для shared
   установите 700. Создайте env dev на основе main с **новыми** `POSTGRES_DB`,
   `POSTGRES_USER`, случайным `POSTGRES_PASSWORD` и согласованным `DATABASE_URL`
   (`db:5432`). Укажите `ORIGIN_API_PORT=28091`, абсолютный `CORPUS_PATH` к общему
   архиву. Main остаётся на 28081 и сохраняет прежние credentials/volume.
2. В каждом origin-каталоге создайте файл `ENVIRONMENT`: `main` или `dev` соответственно.
   Установите туда `infra/ci/origin` как `origin` с правами 755. Настройте JSON выше.
3. Создайте отдельный ключ `~/.ssh/pentada-edge-dev` (ed25519, без passphrase для службы).
   На VPS создайте пользователя `pentada-tunnel-dev` с shell `/usr/sbin/nologin`.
   В его `authorized_keys` разрешите только remote forwarding порта 18091:

   ```text
   restrict,port-forwarding,permitlisten="127.0.0.1:18091",command="/bin/false" ssh-ed25519 <PUBLIC_KEY>
   ```

   Для этого пользователя настройте sshd `PasswordAuthentication no`,
   `AllowTcpForwarding remote`, `PermitListen 127.0.0.1:18091`, `GatewayPorts no`,
   `AllowAgentForwarding no`, `X11Forwarding no`, `PermitTTY no`, `PermitTunnel no`,
   `MaxSessions 0`. Выполните `sshd -t` перед reload. Ключ main не расширяйте.
4. Установите `infra/docker/pentada-dev-tunnel.service` в `~/.config/systemd/user/`,
   создайте `~/.config/pentada-dev-tunnel.env` с `VPS_HOST=<IP>`, права 600.
   Выполните `systemctl --user daemon-reload` и
   `systemctl --user enable --now pentada-dev-tunnel`. Для службы нужен Linger=yes.
5. На VPS установите `infra/ci/edge_receive.py` в `/usr/local/sbin/pentada-edge-receive`
   (root:root, 755). Deploy key в root `authorized_keys` должен иметь ограничения:

   ```text
   restrict,command="/usr/local/sbin/pentada-edge-receive" ssh-ed25519 <DEPLOY_PUBLIC_KEY>
   ```

   Закрытый ключ остаётся на учебном хосте. Alias `pentada-deploy` в SSH config
   указывает на root@VPS, отдельный IdentityFile, BatchMode=yes, IdentitiesOnly=yes,
   StrictHostKeyChecking=yes и проверенный UserKnownHostsFile. Пароль SSH не нужен.
6. Из чистого checkout нового коммита на учебном хосте выполните:

   ```bash
   python3 infra/ci/deploy.py --environment dev --bootstrap
   python3 infra/ci/deploy.py --environment main --bootstrap
   ```

   Bootstrap нужен только до появления gateway: локальные frontend/API всё равно
   проверяются, пропускается только публичный URL. В GitHub Actions флаг запрещён.
7. На VPS скопируйте `compose.gateway.yaml` и `infra/docker/Gateway.Caddyfile` в
   `/opt/pentada/gateway-source/`, сохранив относительные пути. Остановите старый
   frontend проекта `pentada-edge` (без удаления volumes). Запустите:

   ```bash
   docker compose -p pentada-gateway -f /opt/pentada/gateway-source/compose.gateway.yaml up -d --wait
   ```

   Если gateway не поднялся, остановите его и верните старый frontend по сохранённому
   Compose/env; до успешной проверки не удаляйте старые releases и образы.
   Установите `infra/ci/edge-compose` как `/opt/pentada/compose` (755).
8. С ноутбука проверьте оба URL командами ниже, а также redirect `/ → /main/`.
9. Установите обновлённый runner guard и service:

   ```bash
   install -m 700 infra/ci/runner-guard.sh ~/.local/lib/pentada-ci/runner-guard.sh
   install -m 600 infra/ci/pentada-actions-runner.service ~/.config/systemd/user/
   systemctl --user daemon-reload
   systemctl --user enable --now pentada-actions-runner
   ```

Если runner ещё не зарегистрирован, используйте Settings → Actions → Runners →
New self-hosted runner, Linux x64. Скачайте официальный архив, проверьте SHA256,
в каталоге `~/actions-runner-pentada` выполните предложенный config с одноразовым
registration token, `--name pentada-academic --labels pentada-production --work _work`.
Token не сохраняйте в Git/history. Автообновление runner включено.

## Проверки и управление

Вход в публичный `/dev/` выполняется по HTTPS под учётной записью `ruslan2005`.
Контейнер Caddy окружения dev проверяет пароль до обработки страницы, API и статики.
Сохраните bcrypt-хеш пароля (стоимость 10–16) в Actions secret `DEV_AUTH_BCRYPT`.
CI передаёт в релиз файл с хешем, который монтируется в Caddy только для чтения.
При смене пароля обновите секрет и разверните новый коммит dev.

```bash
# С ноутбука, из checkout
python3 scripts/check_production.py --url http://176.12.68.100/main
python3 scripts/check_production.py --url https://smartmail-hackaton.ru/dev --expect-dev-auth

# Учебный хост
~/pentada-astr/origin ps
~/pentada-astr-dev/origin ps
systemctl --user status pentada-actions-runner pentada-edge-tunnel pentada-dev-tunnel
journalctl --user -u pentada-actions-runner -n 50 --no-pager

# VPS
/opt/pentada/compose main ps
/opt/pentada/compose dev ps
/opt/pentada/gateway ps
```

Receiver понимает `current ENV`, `check ENV`, `stage ENV SHA40`, `activate ENV SHA40`
и `deactivate ENV SHA40`. Например:
`ssh -F ~/.ssh/pentada-deploy-config pentada-deploy 'current dev'`.
Произвольные команды и старый протокол без ENV отклоняются.

Backup находится в `<origin_root>/backups/<UTC>-<SHA12>/`. Для отката origin переключите
его `current` на прежний путь из `previous.json`, затем выполните соответствующий
`origin up -d --no-build --wait db backend`. Edge откатывается через
`activate ENV OLD_SHA40`. БД восстанавливайте отдельно после проверки backup.
Старые релизы и backups автоматически не удаляются; контролируйте место. Не запускайте
глобальный prune на общем учебном хосте.

Тесты инфраструктуры: `python3 -m unittest discover -s infra/ci/tests -v`,
`bash -n infra/ci/{origin,edge-compose,runner-guard.sh}`, `actionlint`.

## Границы доступа

PR выполняются на GitHub-hosted runners. Pre-job guard на учебном хосте принимает
только deploy job этого workflow, main/dev и push/workflow_dispatch; другие события
отклоняются до checkout. Однако runner работает от `rusikye` и обе ветки имеют доступ
к production credentials. **Dev изолирован по данным и контейнерам, но не является
песочницей для недоверенного кода.** Право менять main/dev фактически позволяет
развёртывать код на хостах. Forced command тоже не изолирует вредоносный Dockerfile
от root Docker. Для недоверенных участников нужен отдельный deployment account/host.

[GitHub рекомендует закрытые репозитории для self-hosted runners](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners).
[Pre-job hooks](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/run-scripts)
дают дополнительную проверку, а не границу изоляции ОС. Guard и receiver обновляются
администратором отдельно от application deploy.

В релизе dev дополнительный файл `compose.dev-evaluations.yaml` включает оценку моделей.
Сервис prepare создаёт и заполняет БД `enronqa_ru` и `enronqa_en` в PostgreSQL dev.
Архивы берутся из релиза. Успешные прогоны сохраняются в томе `dev_evaluations` проекта Compose.
Вкладка доступна по адресу [Оценка моделей](http://176.12.68.100/dev/#evaluations).
