FROM node:24.11.1-bookworm-slim@sha256:48abc13a19400ca3985071e287bd405a1d99306770eb81d61202fb6b65cf0b57 AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/src ./src
COPY frontend/public ./public
ARG APP_BASE_PATH=/
ENV APP_BASE_PATH=$APP_BASE_PATH
RUN npm run build

FROM caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d
COPY infra/docker/Caddyfile /etc/caddy/Caddyfile
ARG APP_BASE_PATH=/
COPY infra/docker/dev-access.caddy /etc/caddy/dev-access.caddy
RUN if [ "$APP_BASE_PATH" = "/dev/" ]; then cp /etc/caddy/dev-access.caddy /etc/caddy/access.caddy; \
    else touch /etc/caddy/access.caddy; fi
COPY --from=build /app/dist /srv
COPY infra/docker/login /srv-login/
COPY frontend/src/assets/smartmail-logo-vk.png /srv-login/logo.png
COPY frontend/public/fonts/VKSansDisplay-Regular.woff2 /srv-login/font.woff2
