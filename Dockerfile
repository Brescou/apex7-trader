# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .

FROM python:3.12-slim AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN groupadd -r apex7 && useradd -r -g apex7 -d /app apex7
WORKDIR /app
COPY --from=builder --chown=apex7:apex7 /app /app
USER apex7
ENV ANTHROPIC_API_KEY=""
ENV PYTHONUNBUFFERED=1
EXPOSE 8050
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -sf http://localhost:8050/health || exit 1
CMD ["uv", "run", "python", "main.py"]
