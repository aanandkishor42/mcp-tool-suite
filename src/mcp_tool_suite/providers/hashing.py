"""Deterministic, dependency-light offline embeddings.

A hashing / bag-of-words embedding: tokenise, hash each token into a fixed-size
bucket, and L2-normalise. It is not semantic like a real model, but it is free,
instant, reproducible and good enough for tests, demos and CI.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

import numpy as np

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


class HashingEmbeddings:
    name = "hashing"

    def __init__(self, dimension: int = 256) -> None:
        self.dimension = dimension

    def _embed_one(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dimension, dtype=np.float32)
        for token in _TOKEN_RE.findall(text.lower()):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "little") % self.dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector /= norm
        return vector

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text).tolist() for text in texts]
