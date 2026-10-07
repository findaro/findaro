from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ZERCH_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://zerch:zerch@localhost:54329/zerch"
    opensearch_url: str = "http://localhost:19200"
    redis_url: str = "redis://localhost:63799/0"

    # Prefix for every OpenSearch index/alias this deployment owns (lets tests share a cluster).
    index_prefix: str = "zerch"

    # If set, POST /v1/projects requires `Authorization: Bearer <bootstrap_token>`.
    bootstrap_token: str | None = None

    # Embeddings
    embedder: str = "e5"  # "e5" (sentence-transformers) or "hash" (tests / no-model dev)
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_cache_dir: str | None = None
    embedding_batch_size: int = 64

    # LLM (scripts only in M1)
    llm_provider: str = "ollama"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5-5"

    # Search
    search_cache_ttl: int = 60  # seconds; 0 disables
    rrf_k: int = 60
    rank_window: int = 100  # candidates per retriever before fusion
    max_result_window: int = 1000
    knn_k: int = 100
    knn_min_score: float = 0.0  # absolute floor for vector candidates (OpenSearch knn score)
    # Vector candidates scoring more than this below the best vector hit are dropped. Dense scores are
    # compressed, but relevant items sit in a cluster above a visible gap; without a cutoff every
    # query "matches" rank_window documents, which breaks totals, facets and sorted results.
    knn_relative_cutoff: float = 0.02

    # Ingest
    max_upload_mb: int = 50
    max_documents_per_request: int = 10_000
    bulk_batch_size: int = 256
    worker_poll_interval: float = 0.5

    # Rate limit (per key, fixed 1s window); 0 disables
    rate_limit_per_second: int = 50

    cors_origins: str = "*"


@lru_cache
def get_settings() -> Settings:
    return Settings()
