from __future__ import annotations

import hashlib
import re

import numpy as np

_TOKEN = re.compile(r"\w+", re.UNICODE)


class HashEmbedder:
    """Deterministic bag-of-words/char-trigram hashing embedder. For tests and model-free dev only."""

    name = "hash-384"
    dim = 384

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in _TOKEN.findall(text.lower()):
            feats = [tok] + [tok[i : i + 3] for i in range(max(1, len(tok) - 2))]
            for j, feat in enumerate(feats):
                h = int.from_bytes(hashlib.blake2b(feat.encode(), digest_size=8).digest(), "little")
                v[h % self.dim] += (1.0 if (h >> 32) & 1 else -1.0) * (1.0 if j == 0 else 0.3)
        n = np.linalg.norm(v)
        if n == 0:
            v[0] = 1.0
            return v
        return v / n

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.dim), np.float32)

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self.embed_documents(texts)
