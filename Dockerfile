FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_HTTP_TIMEOUT=300 UV_HTTP_RETRIES=5 \
    HF_HOME=/models HF_HUB_DISABLE_TELEMETRY=1
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

# Bake the embedding model into the image as a plain directory, so startup never touches the HF hub.
ARG EMBEDDING_MODEL=intfloat/multilingual-e5-small
RUN /app/.venv/bin/python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('${EMBEDDING_MODEL}').save('/models/embedding')" && rm -rf /models/hub /models/xet

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-editable
ENV PATH="/app/.venv/bin:$PATH" HF_HUB_OFFLINE=1 ZERCH_EMBEDDING_MODEL=/models/embedding
EXPOSE 8000
CMD ["uvicorn", "zerch.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
