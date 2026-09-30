FROM python:3.13-slim AS base
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ripgrep ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && git config --system --add safe.directory '*'
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./

# scripts/deploy.sh builds this stage first: a failing test stops the deploy.
FROM base AS test
RUN uv sync --frozen --no-install-project
COPY src ./src
COPY tests ./tests
RUN uv sync --frozen && uv run --frozen pytest -q -p no:cacheprovider

FROM base
ARG REVISION=unknown
LABEL org.opencontainers.image.revision=$REVISION
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
ENV PATH=/app/.venv/bin:$PATH
USER 1000:1000
CMD ["kzlaw-mcp"]
