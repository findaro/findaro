from __future__ import annotations

import threading

import numpy as np


class E5Embedder:
    """intfloat/multilingual-e5-* via sentence-transformers. E5 needs 'query: ' / 'passage: ' prefixes."""

    def __init__(self, model: str, cache_dir: str | None = None, batch_size: int = 64):
        import torch
        from sentence_transformers import SentenceTransformer

        torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
        self.name = model
        self._model = SentenceTransformer(model, device="cpu", cache_folder=cache_dir)
        self._model.max_seq_length = 256
        get_dim = getattr(self._model, "get_embedding_dimension", None) or self._model.get_sentence_embedding_dimension
        self.dim = int(get_dim())
        self.batch_size = batch_size
        self._lock = threading.Lock()

    def _encode(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            out = self._model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                                     convert_to_numpy=True, show_progress_bar=False)
        return out.astype(np.float32)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._encode([f"passage: {t}" for t in texts])

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._encode([f"query: {t}" for t in texts])
