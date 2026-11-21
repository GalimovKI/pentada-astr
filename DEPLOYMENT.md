# Развёртывание: frontend на VPS, backend на учебном хосте

Инструкция соответствует `main` на коммите `901c4b8` (21 ноября 2026).
Исходники для нового развёртывания берём из актуального `origin/main` и передаём
**один и тот же коммит на оба сервера**. Пароли и закрытые ключи в Git не хранятся.

## Что где работает

Действующая схема с отдельными `/main/` и `/dev/`, двумя БД и автоматическим
обновлением веток описана в [инструкции CI/CD](infra/ci/README.md).
Разделы ниже описывают первоначальную установку одного окружения. Не запускайте
старый frontend на порту 80 поверх нового gateway; переход и команды управления
двумя окружениями приведены в инструкции CI/CD.

```mermaid
flowchart LR
    Browser[Браузер пользователя] -->|HTTP 80 / HTTPS 443| Web[Frontend + Caddy на VPS]
    Web -->|127.0.0.1:18081| SSH[Обратный SSH-туннель]
    SSH -->|127.0.0.1:28081| API[Backend на учебном хосте]
    API --> DB[(PostgreSQL на учебном хосте)]
```

Итого три постоянных контейнера: `web` на VPS, `backend` и `db` на учебном хосте.
`prepare` — временный контейнер миграций и импорта. Туннель запускает учебный
хост через systemd; ноутбук после настройки можно выключить.

| Параметр | Значение для текущего размещения |
| --- | --- |
| VPS | `176.12.68.100`, SSH-пользователь `root`, порт `22` |
| Учебный хост | `rusikye@proxy2.cod.phystech.edu`, SSH-порт `10210` |
| Compose project учебного хоста | `pentada-mailsearch` |
| Compose project VPS | `pentada-edge` |
| API на учебном хосте | Только `127.0.0.1:28081` |
| Вход туннеля на VPS | Только `127.0.0.1:18081` |
| Сайт без домена | <http://176.12.68.100> |

Порт `18081` на учебном хосте ранее был занят, поэтому здесь используется `28081`.
Если он тоже занят, выберите свободный и одинаково задайте `ORIGIN_API_PORT`
в env приложения и env туннеля. На VPS порт туннеля остаётся `18081`.

**Если сайт уже установлен и нужен только запуск:** на VPS выполните
`/opt/pentada/start`, на учебном хосте — `~/pentada-astr/start`.
Для обновления кода используйте раздел «Обновление», а не повторную инициализацию БД.

## 1. Подготовить серверы

Подключение **с ноутбука**, в разных терминалах:

```bash
ssh root@176.12.68.100
ssh -p 10210 rusikye@proxy2.cod.phystech.edu
```

Все дальнейшие команды помечены местом исполнения. Не вводите команды для VPS
в терминал учебного хоста. При другом сервере замените IP и SSH-логин в примерах.

### VPS: Docker и порты

Нужны Linux, Docker Engine, Compose и Buildx. Проверка **на VPS**:

```bash
docker version
docker compose version
docker buildx version
ss -lnt
```

Если Docker ещё не установлен, для Ubuntu используйте
[официальную установку через apt](https://docs.docker.com/engine/install/ubuntu/).
После установки **на VPS от root**:

```bash
systemctl enable --now docker
```

В сетевых правилах провайдера и firewall VPS разрешите входящие TCP `22` и `80`;
для HTTPS дополнительно `443`. Не открывайте `5432`, `8000`, `18081`, `28081`, `8081`.
Порты `80`, `443` и локальный `8081` должны быть свободны для Caddy.

### Учебный хост: пользовательский Docker

В текущем размещении уже установлен rootless Docker. **На учебном хосте**:

```bash
export PATH="$HOME/.local/lib/pentada-docker/bin:$HOME/bin:$PATH"
docker --context rootless version
docker --context rootless compose version
docker --context rootless buildx version
systemctl --user enable --now docker
loginctl show-user "$USER" -p Linger
ss -lnt
```

Нужен `Linger=yes`, чтобы службы переживали выход из SSH и запускались после
перезагрузки. Если linger выключен, администратор хоста выполняет
`sudo loginctl enable-linger rusikye`.

На новом учебном хосте сначала установите
[rootless Docker по официальной инструкции](https://docs.docker.com/engine/security/rootless/)
и плагины Compose/Buildx. Для rootless нужны `newuidmap`, `newgidmap` и диапазоны
в `/etc/subuid` и `/etc/subgid`; при их отсутствии потребуется администратор.
Системный Docker и чужие контейнеры на общем хосте останавливать не надо.
Далее все команды используют явно `--context rootless`.

## 2. Передать свежий main на оба сервера

**На ноутбуке, в корне репозитория:**

```bash
git fetch origin
DEPLOY_COMMIT="$(git rev-parse origin/main)"
DEPLOY_TMP="$(mktemp -d)"
git archive --format=tar.gz "$DEPLOY_COMMIT" > "$DEPLOY_TMP/source.tar.gz"
printf '%s\n' "$DEPLOY_COMMIT" > "$DEPLOY_TMP/RELEASE"
printf 'Разворачиваем коммит: %s\n' "$DEPLOY_COMMIT"

ssh root@176.12.68.100 'mkdir -p /opt/pentada/incoming'
scp "$DEPLOY_TMP/source.tar.gz" "$DEPLOY_TMP/RELEASE" \
  root@176.12.68.100:/opt/pentada/incoming/

ssh -p 10210 rusikye@proxy2.cod.phystech.edu \
  'mkdir -p ~/pentada-astr/incoming'
scp -P 10210 "$DEPLOY_TMP/source.tar.gz" "$DEPLOY_TMP/RELEASE" \
  rusikye@proxy2.cod.phystech.edu:pentada-astr/incoming/
```

Это передаёт только файлы коммита: локальные `.env`, корпус и `node_modules`
не попадают в архив. GitHub-ключ на серверах для такой установки не нужен.

**На VPS:**

```bash
DEPLOY_COMMIT="$(cat /opt/pentada/incoming/RELEASE)"
mkdir -p "/opt/pentada/releases/$DEPLOY_COMMIT"
tar -xzf /opt/pentada/incoming/source.tar.gz -C "/opt/pentada/releases/$DEPLOY_COMMIT"
printf '%s\n' "$DEPLOY_COMMIT" > "/opt/pentada/releases/$DEPLOY_COMMIT/RELEASE_SHA"
ln -sfn "/opt/pentada/releases/$DEPLOY_COMMIT" /opt/pentada/current
```

**На учебном хосте:**

```bash
DEPLOY_COMMIT="$(cat ~/pentada-astr/incoming/RELEASE)"
mkdir -p "$HOME/pentada-astr/releases/$DEPLOY_COMMIT"
tar -xzf ~/pentada-astr/incoming/source.tar.gz -C "$HOME/pentada-astr/releases/$DEPLOY_COMMIT"
printf '%s\n' "$DEPLOY_COMMIT" > "$HOME/pentada-astr/releases/$DEPLOY_COMMIT/RELEASE_SHA"
ln -sfn "$HOME/pentada-astr/releases/$DEPLOY_COMMIT" "$HOME/pentada-astr/current"
install -d -m 700 "$HOME/pentada-astr/shared"
```

При обновлении сначала запишите прежние цели `current` через `readlink` — они
нужны для отката. Не удаляйте предыдущие releases.

## 3. Подготовить корпус и env учебного хоста

### Первая установка

**На ноутбуке** передайте официальный архив только на учебный хост:

```bash
scp -P 10210 data/raw/mipt_mail_search_participants.zip \
  rusikye@proxy2.cod.phystech.edu:pentada-astr/shared/corpus.zip
```

**На учебном хосте** создайте env только если его ещё нет:

```bash
python3 - <<'PY'
from pathlib import Path
import os
import secrets

root = Path.home() / 'pentada-astr'
target = root / 'shared/.env.production'
if target.exists():
    raise SystemExit('env уже существует: сохраните пароль БД и настройки, используйте раздел обновления.')
password = secrets.token_hex(24)
content = (root / 'current/.env.production.example').read_text()
content = content.replace('replace_with_random_password', password)
content = content.replace('CORPUS_PATH=./data/raw/mipt_mail_search_participants.zip',
                          'CORPUS_PATH=' + str(root / 'shared/corpus.zip'))
content += '\nORIGIN_API_PORT=28081\n'
with open(target, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as f:
    f.write(content)
PY
chmod 644 ~/pentada-astr/shared/corpus.zip
```

Корпус должен читаться контейнерным UID `10001`. Родительский каталог `shared`
остаётся закрытым (`0700`); файл монтируется в контейнер read-only.

### Если приложение уже работало

Не генерируйте новый пароль поверх существующей БД и не меняйте имя проекта
`pentada-mailsearch`: к нему привязан прежний volume. Используйте существующий
`~/pentada-astr/shared/.env.production`, сохранив `POSTGRES_*`, `DATABASE_URL`,
`CORPUS_PATH` и согласованные `SEARCH_*`. Проверьте, что архив по `CORPUS_PATH`
существует и читается контейнером. Добавьте или исправьте `ORIGIN_API_PORT=28081`.
Открыть файл для редактирования: `nano ~/pentada-astr/shared/.env.production`.

Новая установка использует текущий default main: `load_event_aware` и
`/app/configs/search/bm25-event-aware.json`. На существующей установке явные
`SEARCH_*` в env имеют приоритет: смена исходников сама по себе не переключает
старый `load_bm25`. Выбирайте фабрику и конфигурацию парой, согласно README.

## 4. Запустить backend и PostgreSQL

**На учебном хосте** создайте команды запуска. Если одноимённые файлы уже есть,
сначала сохраните их копии для отката (`origin.before-update`, `start.before-update`).

```bash
cat > ~/pentada-astr/origin <<'EOF'
#!/bin/sh
set -eu
export PATH="$HOME/.local/lib/pentada-docker/bin:$HOME/bin:$PATH"
export APP_IMAGE_TAG="$(cat "$HOME/pentada-astr/current/RELEASE_SHA")"
exec docker --context rootless compose \
  --env-file "$HOME/pentada-astr/shared/.env.production" \
  -p pentada-mailsearch \
  -f "$HOME/pentada-astr/current/compose.production.yaml" \
  -f "$HOME/pentada-astr/current/compose.origin.yaml" "$@"
EOF
chmod 700 ~/pentada-astr/origin

~/pentada-astr/origin config --quiet
~/pentada-astr/origin build backend
~/pentada-astr/origin run --rm prepare
~/pentada-astr/origin up -d --no-build --wait --wait-timeout 300 db backend
curl --fail http://127.0.0.1:28081/health/ready
```

Ожидается `{"status":"ready"}`. `prepare` применяет миграции и импортирует корпус;
повторный импорт того же набора возвращает `already_imported`.

После первоначальной подготовки достаточно `origin up ...`; импорт не нужен
на каждом старте. При переходе с прежнего размещения старый контейнер `web`
пока оставьте работающим — остановим его после публичной проверки.

## 5. Создать ключ и разрешить туннель

### Учебный хост: отдельный ключ

```bash
install -d -m 700 ~/.ssh
if [ ! -e ~/.ssh/pentada-edge ]; then
  ssh-keygen -t ed25519 -N '' -f ~/.ssh/pentada-edge -C pentada-edge-tunnel
fi
cat ~/.ssh/pentada-edge.pub
```

Скопируйте целиком одну строку `ssh-ed25519 ...`. Закрытый файл `pentada-edge`
остаётся на учебном хосте. Если ключ уже существует, используйте его повторно.

### VPS: пользователь только для туннеля

**На VPS от root:**

```bash
id pentada-tunnel >/dev/null 2>&1 || useradd --create-home --shell /usr/sbin/nologin pentada-tunnel
install -d -m 700 -o pentada-tunnel -g pentada-tunnel /home/pentada-tunnel/.ssh
```

В `/home/pentada-tunnel/.ssh/authorized_keys` должна быть следующая **одна строка**.
Замените `PUBLIC_KEY_FROM_ACADEMIC_HOST` полным публичным ключом из предыдущего шага:

```text
restrict,port-forwarding,permitlisten="127.0.0.1:18081",command="/bin/false" PUBLIC_KEY_FROM_ACADEMIC_HOST
```

Открыть файл на VPS: `nano /home/pentada-tunnel/.ssh/authorized_keys`.
Если файл уже содержит этот ключ, повторно добавлять его не надо. Прочие ключи
не удаляйте. Затем **на VPS**:

```bash
chown pentada-tunnel:pentada-tunnel /home/pentada-tunnel/.ssh/authorized_keys
chmod 600 /home/pentada-tunnel/.ssh/authorized_keys
cat > /etc/ssh/sshd_config.d/pentada-tunnel.conf <<'EOF'
Match User pentada-tunnel
    PasswordAuthentication no
    AllowTcpForwarding remote
    PermitListen 127.0.0.1:18081
    GatewayPorts no
    AllowAgentForwarding no
    X11Forwarding no
    PermitTTY no
    PermitTunnel no
    MaxSessions 0
Match all
EOF
sshd -t && systemctl reload ssh
cat /etc/ssh/ssh_host_ed25519_key.pub
```

Не закрывайте текущую административную SSH-сессию до проверки. Последняя команда
выводит публичный ключ **сервера**, а не пользователя. Получите его через уже
проверенное SSH-соединение (при первом входе сверяйте fingerprint через консоль VPS).

**На учебном хосте** создайте `~/.ssh/pentada-edge-known_hosts` с одной строкой:

```text
176.12.68.100 ssh-ed25519 SERVER_PUBLIC_KEY_BASE64
```

Замените `SERVER_PUBLIC_KEY_BASE64` вторым полем вывода последней команды на VPS.
Открыть файл на учебном хосте: `nano ~/.ssh/pentada-edge-known_hosts`.
Проверка ключа не отключается; один лишь `ssh-keyscan` не подтверждает его подлинность.

## 6. Включить постоянный туннель

**На учебном хосте:**

```bash
chmod 600 ~/.ssh/pentada-edge ~/.ssh/pentada-edge-known_hosts
install -d ~/.config/systemd/user
cat > ~/.config/pentada-edge-tunnel.env <<'EOF'
VPS_HOST=176.12.68.100
ORIGIN_API_PORT=28081
EOF
chmod 600 ~/.config/pentada-edge-tunnel.env
install -m 644 ~/pentada-astr/current/infra/docker/pentada-edge-tunnel.service \
  ~/.config/systemd/user/pentada-edge-tunnel.service
systemd-analyze --user verify ~/.config/systemd/user/pentada-edge-tunnel.service
systemctl --user daemon-reload
systemctl --user enable pentada-edge-tunnel
systemctl --user restart pentada-edge-tunnel
systemctl --user status pentada-edge-tunnel --no-pager
```

**На VPS:**

```bash
curl --fail http://127.0.0.1:18081/health/ready
ss -lnt | grep ':18081'
```

Ожидается `ready`, порт должен слушать `127.0.0.1`. Служба восстанавливает
соединение после обрыва. На VPS для этого не нужны пароль или ключ учебного хоста.

**На учебном хосте** создайте короткую команду обычного запуска:

```bash
cat > ~/pentada-astr/start <<'EOF'
#!/bin/sh
set -eu
"$HOME/pentada-astr/origin" up -d --no-build --wait --wait-timeout 300 db backend
systemctl --user start pentada-edge-tunnel
EOF
chmod 700 ~/pentada-astr/start
```

## 7. Собрать и запустить frontend на VPS

**На VPS от root** создайте wrapper. Существующие `compose` и `start` сначала
сохраните под именами `compose.before-update` и `start.before-update`.

```bash
cat > /opt/pentada/compose <<'EOF'
#!/bin/sh
set -eu
export APP_IMAGE_TAG="$(cat /opt/pentada/current/RELEASE_SHA)"
exec docker compose --env-file /opt/pentada/edge.env \
  -p pentada-edge -f /opt/pentada/current/compose.edge.yaml "$@"
EOF
if [ ! -f /opt/pentada/edge.env ]; then
  printf '%s\n' 'SITE_ADDRESS=http://:80' 'TUNNEL_PORT=18081' > /opt/pentada/edge.env
fi
cat > /opt/pentada/start <<'EOF'
#!/bin/sh
set -eu
exec /opt/pentada/compose up -d --build --wait --wait-timeout 300
EOF
chmod 755 /opt/pentada/compose /opt/pentada/start
/opt/pentada/start
```

После настройки это **одна команда сборки и запуска frontend**: `/opt/pentada/start`.
Caddy использует Linux host networking, поэтому видит локальный порт туннеля.
На VPS не нужны корпус, PostgreSQL или env с паролем базы.

## 8. Проверить сайт с ноутбука

**На ноутбуке, из checkout того же коммита, что развёрнут на серверах:**

```bash
curl --fail http://176.12.68.100/health/ready
python3 scripts/check_production.py --url http://176.12.68.100
```

Откройте <http://176.12.68.100> в браузере, выберите ящик, найдите письмо и откройте его.
Для полной проверки 99 запросов нужен официальный архив и Python-окружение:

```bash
uv sync --project backend --locked
uv run --project backend --locked python scripts/check_http_api.py --url http://176.12.68.100
```

Эта проверка сравнивает API с локальным движком. Если сервер использует нестандартные
`SEARCH_ENGINE_FACTORY`/`SEARCH_CONFIG`, передайте проверке ту же фабрику и локальный
путь к той же конфигурации; контейнерный путь `/app/...` на ноутбуке не подходит.

После успешной проверки **на учебном хосте** остановите прежний `web`, если он есть:

```bash
~/pentada-astr/origin --profile local-web stop web
~/pentada-astr/origin ps
```

Должны остаться два работающих контейнера — `db` и `backend`.
**На VPS** `/opt/pentada/compose ps` должен показывать один работающий `web`.
Старую команду `~/pentada-astr/compose` для запуска учебного хоста больше не
используйте: она может убрать loopback-порт backend или запустить старый frontend.

## 9. Подключить домен и HTTPS (необязательно)

1. В DNS домена создайте A-запись на `176.12.68.100`. AAAA добавляйте только при
   рабочем IPv6. Домен можно купить отдельно от VPS.
2. Разрешите входящие TCP `80` и `443` на VPS.
3. В `/opt/pentada/edge.env` замените `SITE_ADDRESS=http://:80` на
   `SITE_ADDRESS=ваш-домен.ru`, без `http://`.
4. На VPS выполните `/opt/pentada/start`.
5. Проверьте открытие `https://ваш-домен.ru` и перенаправление с HTTP.

Caddy хранит сертификаты в volume `caddy_data`. Подробности условий выпуска:
[Automatic HTTPS](https://caddyserver.com/docs/automatic-https).
По IP в основной инструкции используется HTTP; включение TLS — отдельный шаг.

## 10. Обновление, остановка и откат

### Обновление

Сначала сохраните старые targets `current`, wrappers и env-файлы.
Сделайте резервную копию БД **на учебном хосте**:

```bash
install -d -m 700 ~/pentada-astr/backups
umask 077
~/pentada-astr/origin exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "$HOME/pentada-astr/backups/before-update-$(date -u +%Y%m%dT%H%M%SZ).dump"
```

Передайте новую версию по разделу 2. Если wrappers уже созданы по этой инструкции,
они читают `current`; переписывать их на каждом обновлении не нужно.
Сохраните существующие пароли, имя проекта и настройки поиска. Затем:

- Учебный хост: `~/pentada-astr/origin build backend`,
  `~/pentada-astr/origin run --rm prepare`, `~/pentada-astr/start`.
- При изменении unit туннеля повторите раздел 6.
- VPS: `/opt/pentada/start`.
- Повторите внешнюю проверку из раздела 8.

Обновление допускает короткий перерыв. Readiness должен стать успешным прежде,
чем обновление считается завершённым. Корпус с другим fingerprint требует отдельного
плана миграции; обычный импорт поверх прежнего набора его не заменяет.

### Остановка без удаления данных

- VPS: `/opt/pentada/compose stop`.
- Учебный хост: `systemctl --user stop pentada-edge-tunnel`, затем
  `~/pentada-astr/origin stop backend db`.
- Запуск снова: сначала `~/pentada-astr/start` на учебном хосте, потом
  `/opt/pentada/start` на VPS.

Не выполняйте `down -v`: это удаляет volumes БД и сертификатов.

### Откат

Верните `current` на сохранённые releases на обоих серверах; восстановите env
и wrappers, если они менялись. Для release без `RELEASE_SHA` используйте его старый
wrapper. Запустите прежние образы и повторите внешнюю проверку. Если миграция новой
версии несовместима со старым backend, простого переключения кода недостаточно:
потребуется согласованное восстановление дампа по разделу PostgreSQL в README.

## 11. Если что-то не работает

| Симптом | Что проверить |
| --- | --- |
| Сайт не открывается | VPS включён; `/opt/pentada/compose ps`; порт 80 в правилах провайдера/firewall; `ss -lnt` на VPS |
| Статика есть, API возвращает 502 | На VPS `curl --fail http://127.0.0.1:18081/health/ready`; затем status/logs туннеля на учебном хосте |
| Туннель active, API недоступен | На учебном хосте `curl --fail http://127.0.0.1:28081/health/ready`; совпадают ли оба `ORIGIN_API_PORT` |
| API возвращает 503 | `~/pentada-astr/origin logs --tail=100 backend`; миграции/импорт, корпус, фабрика и путь конфигурации |
| Permission denied при SSH | Публичный ключ, владелец/права authorized_keys, настройка Match User на VPS |
| Host key verification failed | Сверить реальный host key через консоль VPS и исправить known_hosts; не отключать проверку |
| Address already in use | Проверить `ss -lnt`; выбрать свободный origin-порт, не останавливать чужой процесс |
| После выхода из SSH всё останавливается | `Linger=yes`, `systemctl --user is-enabled docker pentada-edge-tunnel` |
| Корпус не читается | `CORPUS_PATH` существует, файл доступен контейнерному UID, mount read-only |

Логи туннеля **на учебном хосте**:

```bash
journalctl --user -u pentada-edge-tunnel -n 100 --no-pager
```

Логи frontend **на VPS**:

```bash
/opt/pentada/compose logs --tail=100 web
```

Не публикуйте env-файлы, пароли, закрытые ключи и полный вывод `compose config`.
Для проверки конфигурации достаточно `config --quiet`.
