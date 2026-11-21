FROM ghcr.io/astral-sh/uv:0.9.11@sha256:5aa820129de0a600924f166aec9cb51613b15b68f1dcd2a02f31a500d2ede568 AS uv
FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS python-base

FROM python-base AS dependencies
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_HTTP_TIMEOUT=120
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
ARG TARGETARCH
ARG INCLUDE_MINILM=0
ARG MINILM_DEVICE=cpu
ARG E5_DEVICE=cpu
RUN --mount=type=cache,id=pentada-uv-${TARGETARCH},target=/root/.cache/uv \
    if [ "$MINILM_DEVICE" = "cuda" ]; then set -- --extra minilm-gpu; \
    elif [ "$E5_DEVICE" = "cuda" ]; then set -- --extra e5-gpu; \
    elif [ "$INCLUDE_MINILM" = "1" ]; then set -- --extra minilm; else set --; fi; \
    uv sync --locked --no-dev --no-editable --no-install-project --python /usr/local/bin/python "$@"

# Source edits rebuild only the installed application, not its dependencies.
FROM dependencies AS build
COPY backend/src ./src
RUN --mount=type=cache,id=pentada-uv-${TARGETARCH},target=/root/.cache/uv \
    uv build --wheel --out-dir /dist

# Model stages depend only on the fetch scripts, platform and model arguments.
# Keep MiniLM and E5 independent of each other and of the Python environment.
FROM python-base AS model-fetch
COPY infra/docker/fetch_minilm.py /tmp/fetch_minilm.py

FROM model-fetch AS minilm-model
ARG INCLUDE_MINILM=0
ARG MINILM_DEVICE=cpu
ARG TARGETARCH
RUN mkdir -p /opt/mailsearch/minilm && \
    if [ "$INCLUDE_MINILM" = "1" ]; then \
      python /tmp/fetch_minilm.py --arch "${TARGETARCH:-$(uname -m)}" --device "$MINILM_DEVICE" --output /opt/mailsearch/minilm; \
    fi

FROM model-fetch AS e5-model
ARG INCLUDE_MINILM=0
ARG E5_DEVICE=cpu
COPY infra/docker/fetch_e5.py /tmp/fetch_e5.py
RUN mkdir -p /opt/mailsearch/e5 && \
    if [ "$INCLUDE_MINILM" = "1" ]; then python /tmp/fetch_e5.py --device "$E5_DEVICE" --output /opt/mailsearch/e5; fi

FROM python-base AS runtime
ENV PATH="/app/backend/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN useradd --uid 10001 --create-home app && install -d -o app -g app /home/app/evaluations /home/app/e5-indexes
COPY --from=minilm-model /opt/mailsearch/minilm /opt/mailsearch/minilm
COPY --from=e5-model /opt/mailsearch/e5 /opt/mailsearch/e5
COPY --from=dependencies /app/backend/.venv /app/backend/.venv
# Install only our wheel on top of the stable dependency layer, without network.
# Bind mounts keep the build tool and wheel out of the final image.
RUN --network=none --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    --mount=from=build,source=/dist,target=/tmp/pentada-dist \
    uv pip install --python /app/backend/.venv/bin/python --no-deps --no-cache --offline /tmp/pentada-dist/*.whl
# Keep the existing repository_root locator working for installed CLI commands.
COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY PROJECT.md /app/PROJECT.md
COPY backend/alembic.ini /app/backend/alembic.ini
COPY backend/migrations /app/backend/migrations
COPY configs/search /app/configs/search
COPY infra/docker/prepare.py /app/infra/docker/prepare.py
COPY scripts/check_minilm_gpu.py /app/scripts/check_minilm_gpu.py
USER app
EXPOSE 8000
CMD ["uvicorn", "mail_search.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
