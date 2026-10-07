"""Embedding interface. Implementations must return L2-normalised float32 vectors."""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_queries(self, texts: list[str]) -> np.ndarray: ...


@lru_cache
def get_embedder(kind: str | None = None) -> Embedder:
    from zerch.config import get_settings

    s = get_settings()
    kind = kind or s.embedder
    if kind == "hash":
        from zerch.embeddings.hashing import HashEmbedder

        return HashEmbedder()
    if kind == "e5":
        from zerch.embeddings.e5 import E5Embedder

        return E5Embedder(s.embedding_model, cache_dir=s.embedding_cache_dir, batch_size=s.embedding_batch_size)
    raise ValueError(f"unknown embedder {kind!r}")
