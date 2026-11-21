# GitHub Actions: проверки и развёртывание на двух хостах

Workflow: [`.github/workflows/ci-cd.yml`](../../.github/workflows/ci-cd.yml).
Основа установки серверов, корпуса и туннеля — [DEPLOYMENT.md](../../DEPLOYMENT.md).
Модель и поисковая конфигурация этим workflow не изменяются.

## Что запускается

Для PR в `main` и push в `main` GitHub-hosted runners проверяют backend
с отдельным тестовым PostgreSQL, frontend unit tests, TypeScript/Vite build
и Playwright на desktop/mobile. Корпус для этих тестов не нужен: используются fixtures.

После успешных проверок push в `main` запускает `deploy` на `pentada-academic`.
Есть ручной `Run workflow`, разрешённый для `main`. Прямой push в `main` также
считается обновлением; для обязательного MR настройте branch protection.
Устаревший запуск пропускается, если в `main` уже появился новый коммит.
Деплои выполняются последовательно, начатый деплой не отменяется новым push.

Runner архивирует точный коммит, собирает backend на учебном хосте и frontend
на VPS. До завершения обеих сборок работающие контейнеры не меняются. Затем
создаётся `pg_dump`, выполняется prepare, обновляется backend, после его готовности
— frontend. Проверяются публичные HTML/assets, readiness, API и список ящиков.
На каждом хосте остаются `releases/<полный SHA>` и ссылка `current`.

При ошибке после начала переключения скрипт пытается вернуть прежние контейнеры
и ссылки. БД автоматически не восстанавливается. Изменение файлов
`backend/migrations/` останавливает автоматическое обновление: сначала выполните
плановое ручное развёртывание по DEPLOYMENT.md, включая обновление `current`,
затем повторите workflow. Обновление контейнера может дать короткий перерыв API;
это не схема zero downtime.

## Уже установленная конфигурация

- Repo runner `pentada-academic`, Linux x64, label `pentada-production`.
- Учебный хост: `~/actions-runner-pentada`, user systemd unit
  `pentada-actions-runner.service`, автозапуск и linger включены.
- Данные и пароль БД: `~/pentada-astr/shared`, вне `_work` runner.
- Origin: `~/pentada-astr`, rootless Docker, проект `pentada-mailsearch`, порт 28081.
- Edge: `176.12.68.100`, `/opt/pentada`, проект `pentada-edge`.
- Настройки runner: `~/.config/pentada-ci.json` (600).
- Отдельный ключ `~/.ssh/pentada-deploy` (600), SSH config
  `~/.ssh/pentada-deploy-config`; host key проверяется по
  `~/.ssh/pentada-edge-known_hosts`.
- На VPS ключ разрешает только `/usr/local/sbin/pentada-edge-receive`.
  Пароль root не нужен workflow и не хранится в GitHub Secrets.
- Туннель `pentada-edge-tunnel.service` продолжает работать независимо от runner.

Workflow начнёт работать только после публикации этой ветки и её merge в `main`.
Установка runner сама по себе не публикует workflow.

## Повторная установка runner

На GitHub откройте Settings → Actions → Runners → New self-hosted runner,
выберите Linux / x64. Скачайте официальный архив в `~/actions-runner-pentada`,
проверьте SHA256, распакуйте. Выполните предложенный `config.sh` с одноразовым
registration token, добавив:

```bash
--name pentada-academic --labels pentada-production --work _work
```

Не сохраняйте token в репозитории или shell history. Постоянный PAT runner не нужен.
Для первоначальной установки использован runner 2.338.2; автообновление оставлено
включённым. Если отсутствуют системные зависимости, их устанавливает администратор
учебного хоста по официальной инструкции GitHub.

Из checkout на учебном хосте:

```bash
mkdir -p ~/.local/lib/pentada-ci ~/.config/systemd/user
install -m 700 infra/ci/runner-guard.sh ~/.local/lib/pentada-ci/runner-guard.sh
install -m 600 infra/ci/pentada-actions-runner.service ~/.config/systemd/user/
install -m 755 infra/ci/origin ~/pentada-astr/origin
systemctl --user daemon-reload
systemctl --user enable --now pentada-actions-runner
```

Для работы после logout нужен `loginctl show-user "$USER" -p Linger` → `yes`.
Если это не так, попросите администратора включить linger для вашей учётной записи.

Создайте `~/.config/pentada-ci.json` с правами 600:

```json
{
  "origin_root": "~/pentada-astr",
  "docker": "~/.local/lib/pentada-docker/bin/docker",
  "ssh_config": "~/.ssh/pentada-deploy-config",
  "public_url": "http://176.12.68.100"
}
```

Адрес, пути и origin-порт должны соответствовать вашей установке. Скрипты
используют существующий `shared/.env.production`, не печатая пароль БД.
Тег образа выбирается по имени каталога релиза и перекрывает `APP_IMAGE_TAG` из env.
Настройки поиска остаются теми, что заданы в production env.

## Ключ и обработчик VPS

На учебном хосте создайте отдельный ключ (не перезаписывайте существующий):

```bash
ssh-keygen -t ed25519 -N '' -C pentada-ci-deploy -f ~/.ssh/pentada-deploy
cat ~/.ssh/pentada-deploy.pub
```

На VPS от root установите из проверенного checkout:

```bash
install -o root -g root -m 755 infra/ci/edge_receive.py /usr/local/sbin/pentada-edge-receive
install -m 755 infra/ci/edge-compose /opt/pentada/compose
install -d -m 700 /root/.ssh
```

Добавьте в `/root/.ssh/authorized_keys` строку, подставив **публичную** часть нового
ключа; остальные строки сохраните:

```text
restrict,command="/usr/local/sbin/pentada-edge-receive" ssh-ed25519 <PUBLIC_KEY> pentada-ci-deploy
```

SSH config на учебном хосте (`~/.ssh/pentada-deploy-config`, права 600):

```sshconfig
Host pentada-deploy
  HostName 176.12.68.100
  User root
  IdentityFile ~/.ssh/pentada-deploy
  IdentitiesOnly yes
  BatchMode yes
  StrictHostKeyChecking yes
  UserKnownHostsFile ~/.ssh/pentada-edge-known_hosts
  ServerAliveInterval 30
  ServerAliveCountMax 3
  ConnectTimeout 15
```

Host key сверяйте через доверенную консоль VPS, как в DEPLOYMENT.md. Проверка:

```bash
ssh -F ~/.ssh/pentada-deploy-config pentada-deploy current
ssh -F ~/.ssh/pentada-deploy-config pentada-deploy id  # должен завершиться отказом
```

Обработчик принимает только `current`, `stage SHA` (архив через stdin) и
`activate SHA`. Он блокирует traversal и ссылки в архиве. Но сборка и запуск
контейнеров через root Docker означают доверие публикуемому коду: forced command
не превращает вредоносный Dockerfile/Compose в безопасный. Файл обработчика и
runner guard обновляются администратором отдельно, не самим деплоем.

## Публичный репозиторий и доступ

GitHub [не рекомендует self-hosted runners для публичных репозиториев](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners).
В этом workflow PR работают на GitHub-hosted runners. Дополнительный
[pre-job hook](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/run-scripts)
на учебном хосте допускает только `deploy` из указанного workflow в `main`,
события `push`/`workflow_dispatch`. Ошибка проверки останавливает job до checkout.
Это дополнительная проверка, а не отдельная граница изоляции ОС.

Runner работает с правами `rusikye` и доступом к production env. Право изменять
`main` фактически даёт право развёртывать код на обоих хостах. Не подтверждайте
запуски посторонних workflow на этом runner, проверяйте изменения CI и Compose
в MR. Для команды с недоверенными участниками нужен изолированный deployment
host/аккаунт или закрытый deployment repository.

## Статус и ручное восстановление

```bash
# Учебный хост
systemctl --user status pentada-actions-runner
journalctl --user -u pentada-actions-runner -n 50 --no-pager
~/pentada-astr/origin ps
systemctl --user status pentada-edge-tunnel
# VPS
/opt/pentada/compose ps
```

Backup: `~/pentada-astr/backups/<UTC>-<SHA12>/`: `database.dump`, копия env и
`previous.json` с обоими предыдущими релизами. Для ручного отката origin
переключите `current` на сохранённый путь и выполните
`~/pentada-astr/origin up -d --no-build --wait db backend`. Edge можно вернуть
командой `ssh -F ~/.ssh/pentada-deploy-config pentada-deploy 'activate <OLD_SHA>'`.
Восстановление БД выполняйте отдельно по DEPLOYMENT.md после проверки backup.

Если автоматический откат также завершился ошибкой, job остаётся failed:
проверьте контейнеры обоих хостов и восстановите их вручную. Runner не удаляет
volumes, backups и старые образы. Следите за `df -h` и `docker system df`;
периодически удаляйте только проверенные старые релизы/образы этого проекта,
сохраняя текущий релиз и рабочий вариант для отката. Глобальный prune на общем
учебном Docker не выполняйте.

Проверки инфраструктурного кода:

```bash
python3 -m unittest discover -s infra/ci/tests -v
bash -n infra/ci/runner-guard.sh infra/ci/origin infra/ci/edge-compose
actionlint
```
