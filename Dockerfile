# syntax=docker/dockerfile:1
# APEX-7 — multi-stage: build deps with uv, run without uv in final image (Finding 7.1)

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml ./

RUN uv sync --no-dev

# -----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /usr/sbin/nologin appuser

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Pass at runtime: ANTHROPIC_API_KEY (required for live LLM; do not bake secrets into the image).
# Example: docker run -e ANTHROPIC_API_KEY=sk-ant-api03-...

COPY --chown=appuser:appuser . .

RUN chown -R appuser:appuser /app/.venv

USER appuser

EXPOSE 8050

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8050/health || exit 1

# Equivalent to `uv run python main.py` — venv is on PATH (no uv in runtime image).
CMD ["python", "main.py"]
