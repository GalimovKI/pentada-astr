FROM ghcr.io/astral-sh/uv:0.9.11@sha256:5aa820129de0a600924f166aec9cb51613b15b68f1dcd2a02f31a500d2ede568 AS uv
FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/src ./src
RUN uv sync --locked --no-dev --no-editable --no-cache --python /usr/local/bin/python

FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS runtime
ENV PATH="/app/backend/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --from=build /app/backend/.venv /app/backend/.venv
# Keep the existing repository_root locator working for installed CLI commands.
COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY PROJECT.md /app/PROJECT.md
COPY backend/alembic.ini /app/backend/alembic.ini
COPY backend/migrations /app/backend/migrations
COPY configs/search /app/configs/search
COPY infra/docker/prepare.py /app/infra/docker/prepare.py
RUN useradd --uid 10001 --create-home app && install -d -o app -g app /home/app/evaluations
USER app
EXPOSE 8000
CMD ["uvicorn", "mail_search.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
