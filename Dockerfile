# Fallback Dockerfile for manual Render Web Service creation from the repo root.
# The Blueprint uses server/Dockerfile through rootDir: server.
FROM python:3.13-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    FASTEMBED_CACHE_PATH=/app/.fastembed_cache

COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY server/app ./app
COPY server/data ./data

RUN uv run python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
