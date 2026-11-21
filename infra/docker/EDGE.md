# Frontend на VPS, backend на учебном хосте

Схема: браузер → публичный Caddy на VPS → SSH-туннель → backend:8000
на учебном хосте → PostgreSQL. Статика собирается и обслуживается на VPS.
Ноутбук пользователя в соединении не участвует. Поисковая конфигурация не меняется.

Нужны Linux VPS с Docker Engine/Compose и SSH-доступом, а также исходящий SSH
с учебного хоста к VPS. На VPS доступны входящие TCP 22 и 80 (443 для домена
с HTTPS). Порты PostgreSQL и туннеля не публикуются в интернете.

## Учебный хост

Используйте прежние env, имя Compose project и release, чтобы сохранить базу,
модель и образы. Добавьте `compose.origin.yaml` вторым `-f` к существующей
команде Compose. Для первоначального перехода достаточно:

```bash
docker compose --env-file .env.production -p mailsearch-demo \
  -f compose.production.yaml -f compose.origin.yaml up -d --no-build --wait db backend
```

Если развёртывание использует другое имя проекта, замените `mailsearch-demo`
на него; не создавайте новый проект поверх существующего развёртывания.
Backend публикуется только на `127.0.0.1:18081`. Создайте отдельный SSH-ключ:

```bash
install -d -m 700 ~/.ssh
ssh-keygen -t ed25519 -N '' -f ~/.ssh/pentada-edge -C pentada-edge-tunnel
```

Не перезаписывайте существующий ключ. Передайте на VPS только `.pub`.

## SSH на VPS

Создайте отдельного пользователя `pentada-tunnel` для ключа, без интерактивного
доступа. В его `.ssh/authorized_keys` разместите публичный ключ с префиксом:

```text
restrict,port-forwarding,permitlisten="127.0.0.1:18081",command="/bin/false" ssh-ed25519 ...
```

В отдельном файле `/etc/ssh/sshd_config.d/pentada-tunnel.conf`:

```text
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
```

Проверьте `sshd -t` до reload службы SSH и сохраните текущую SSH-сессию.
Каталог `.ssh` должен принадлежать `pentada-tunnel`, права 0700;
`authorized_keys` — 0600. Не меняйте правила входа администратора.

Через уже проверенное SSH-соединение прочитайте публичный host key VPS
`/etc/ssh/ssh_host_ed25519_key.pub`. Сохраните его на учебном хосте как
`~/.ssh/pentada-edge-known_hosts` в формате `VPS_IP ssh-ed25519 KEY`.
Сам по себе результат `ssh-keyscan` не подтверждает подлинность сервера.

## Постоянный туннель

На учебном хосте создайте `~/.config/pentada-edge-tunnel.env`:

```text
VPS_HOST=YOUR_VPS_IP
ORIGIN_API_PORT=18081
```

Установите приложенный user unit:

```bash
install -d ~/.config/systemd/user
install -m 644 infra/docker/pentada-edge-tunnel.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pentada-edge-tunnel
systemctl --user status pentada-edge-tunnel
```

Для работы после выхода и перезагрузки администратор должен включить linger
для пользователя учебного хоста. Проверка: `loginctl show-user "$USER" -p Linger`.
На VPS `curl http://127.0.0.1:18081/health/ready` должен вернуть `ready`.
Unit повторяет соединение после обрыва. Если на учебном хосте порт 18081 занят,
выберите свободный и задайте одинаковый `ORIGIN_API_PORT` в окружении Compose
и в файле туннеля. На VPS порт остаётся 18081; при его смене согласуйте unit,
edge Compose и `PermitListen`.

## Frontend на VPS

Скопируйте исходники нужного коммита без корпуса, моделей и `.env.production`.
В корне проекта на VPS сборка и запуск выполняются одной командой:

```bash
docker compose -p pentada-edge -f compose.edge.yaml up -d --build --wait
```

Используется Linux host networking, чтобы Caddy видел loopback-порт туннеля.
По умолчанию сайт работает по `http://VPS_IP`; HTTPS требует отдельной настройки
домена. Для домена задайте `SITE_ADDRESS=example.ru` в окружении Compose и
направьте его DNS на VPS. Caddy хранит сертификаты в named volume.

Проверка с внешнего компьютера:

```bash
python3 scripts/check_production.py --url http://VPS_IP
uv run --project backend --locked python scripts/check_http_api.py --url http://VPS_IP
```

Проверьте поиск и чтение письма в браузере. После успешного перехода остановите
прежний `web` на учебном хосте через старую команду Compose: останутся ровно
три работающих контейнера — `web` на VPS, `backend` и `db` на учебном хосте.
Не используйте `down -v`: это удаляет данные.

## Эксплуатация и откат

- VPS: `docker compose -p pentada-edge -f compose.edge.yaml ps`, `logs --tail=100 web`.
- Учебный хост: `systemctl --user status pentada-edge-tunnel`,
  `journalctl --user -u pentada-edge-tunnel -n 50 --no-pager`.
- При недоступном API проверьте сначала `/health/ready` на loopback VPS,
  затем loopback учебного хоста. Frontend healthcheck проверяет только Caddy;
  успешный статус контейнера не доказывает работоспособность поиска.
- Откат: остановите edge и unit туннеля, запустите прежний `web` на учебном хосте
  через прежний Compose. База и модель остаются прежними.

Секреты, закрытый SSH-ключ и env с паролем БД не включаются в исходники.
