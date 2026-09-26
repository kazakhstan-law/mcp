FROM python:3.13-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ripgrep ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && git config --system --add safe.directory '*'
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
ENV PATH=/app/.venv/bin:$PATH
USER 1000:1000
CMD ["kzlaw-mcp"]
