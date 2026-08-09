# Backend Ardoise — FastAPI + LangGraph + fastembed. Image auto-suffisante :
# le modèle d'embeddings est téléchargé au build → cold-start rapide.
FROM python:3.13-slim

# onnxruntime (via fastembed) a besoin de libgomp1.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

# uv (gestionnaire de paquets rapide)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    FASTEMBED_CACHE_PATH=/app/.fastembed_cache

# 1) Dépendances (couche cachée tant que les lock ne changent pas)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2) Code + données
COPY app ./app
COPY data ./data

# 3) Pré-télécharge le modèle d'embeddings dans l'image
RUN uv run python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
