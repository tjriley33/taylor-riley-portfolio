"""Embedding + cross-encoder wrappers (fastembed, ONNX, CPU, local)."""
from __future__ import annotations

import threading
from typing import Iterable

import numpy as np

from ..config import settings

_lock = threading.Lock()
_embedder = None
_reranker = None


def embedder():
    global _embedder
    with _lock:
        if _embedder is None:
            from fastembed import TextEmbedding
            settings.model_cache_dir.mkdir(parents=True, exist_ok=True)
            _embedder = TextEmbedding(model_name=settings.embed_model, cache_dir=str(settings.model_cache_dir), threads=4)
        return _embedder


def embed_passages(texts: list[str], batch_size: int = 32) -> np.ndarray:
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    vecs = list(embedder().passage_embed(texts, batch_size=batch_size))
    return np.vstack([np.asarray(v, dtype=np.float32) for v in vecs])


def embed_query(text: str) -> np.ndarray:
    v = list(embedder().query_embed([text]))[0]
    return np.asarray(v, dtype=np.float32)


def reranker():
    global _reranker
    with _lock:
        if _reranker is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            settings.model_cache_dir.mkdir(parents=True, exist_ok=True)
            _reranker = TextCrossEncoder(model_name=settings.rerank_model, cache_dir=str(settings.model_cache_dir), threads=4)
        return _reranker


def cross_scores(query: str, passages: list[str]) -> list[float]:
    if not passages:
        return []
    return [float(s) for s in reranker().rerank(query, passages, batch_size=16)]
