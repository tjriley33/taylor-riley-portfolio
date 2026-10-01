"""Hybrid retrieval: filter-first vector + BM25, RRF fusion, graph expansion, reranking, parent expansion."""
from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from ..config import settings
from ..embed import embed_query
from ..models import RetrievedChunk
from ..store import Store
from .conflicts import detect_conflicts
from .expand import expand_graph, attach_parents
from .query import QueryPlan
from .rerank import rerank


class RetrievalResult(BaseModel):
    plan: QueryPlan
    candidates: list[RetrievedChunk] = Field(default_factory=list)
    context: list[RetrievedChunk] = Field(default_factory=list)
    conflicts: list[dict] = Field(default_factory=list)
    confidence: float = 0.0
    sufficient: bool = False
    relaxations: list[str] = Field(default_factory=list)
    latency_ms: dict[str, float] = Field(default_factory=dict)
    filters_used: dict[str, Any] = Field(default_factory=dict)


def _rrf(rankings: list[list[tuple[str, float]]], k: int = 60) -> dict[str, float]:
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, (cid, _) in enumerate(ranking):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return fused


def _apply_fallbacks(store: Store, plan: QueryPlan, filters: dict) -> tuple[dict, list[str]]:
    """Relax filters that would return nothing, and say so. Draft fallback only when no final exists."""
    notes: list[str] = []
    f = dict(filters)
    if store.count_chunks({**f, "strategy": settings.chunk_strategy}) > 0:
        return f, notes
    if f.get("draft_or_final") == "final":
        g = {**f, "draft_or_final": None}
        if store.count_chunks({**g, "strategy": settings.chunk_strategy}) > 0:
            notes.append("No final documents matched; including DRAFT documents (labelled).")
            return g, notes
    # Jurisdiction and tax year are never relaxed silently: an answer from the wrong state or year is worse than no answer.
    if "jurisdiction" in f and f["jurisdiction"] is not None and store.count_chunks({"jurisdiction": f["jurisdiction"], "strategy": settings.chunk_strategy}) == 0:
        notes.append(f"No documents for jurisdiction {f['jurisdiction']} are indexed. Nothing to cite.")
    elif "tax_year" in f and f["tax_year"] is not None:
        notes.append(f"No documents for tax year {f['tax_year']} matched the requested scope. Nothing to cite for that year.")
    return f, notes


def retrieve(store: Store, plan: QueryPlan, strategy: str | None = None, k_context: int | None = None,
             expand: bool = True, use_reranker: bool | None = None, query_text: str | None = None) -> RetrievalResult:
    strategy = strategy or settings.chunk_strategy
    k_context = k_context or settings.context_k
    lat: dict[str, float] = {}
    t0 = time.perf_counter()
    filters, relaxations = _apply_fallbacks(store, plan, plan.hard_filters)
    filters = {**filters, "strategy": strategy, "version_status": None}
    lat["filters"] = (time.perf_counter() - t0) * 1000

    qtext = query_text or plan.question
    t = time.perf_counter()
    bm25 = store.fts_search(plan.fts_query(), filters, k=settings.bm25_k)
    # second lexical pass with the raw question for recall
    bm25_raw = store.fts_search(" OR ".join(f'"{w}"' for w in plan.topic.split()[:10] if len(w) > 2) or '"tax"', filters, k=settings.bm25_k // 2)
    lat["bm25"] = (time.perf_counter() - t) * 1000

    t = time.perf_counter()
    try:
        qvec = embed_query(qtext)
        vec = store.vector_search(qvec, filters, settings.embed_model, strategy, k=settings.vector_k)
    except Exception as e:  # noqa: BLE001  (embedding model missing -> lexical only)
        vec = []
        relaxations.append(f"vector search unavailable: {e}")
    lat["vector"] = (time.perf_counter() - t) * 1000

    fused = _rrf([vec, bm25, bm25_raw])
    vec_d, bm_d = dict(vec), dict(bm25)
    bm_raw_d = dict(bm25_raw)
    rows = store.get_chunks(list(fused))
    cands: list[RetrievedChunk] = []
    for cid, score in fused.items():
        ch = rows.get(cid)
        if not ch:
            continue
        reasons = []
        if cid in vec_d:
            reasons.append(f"vector sim {vec_d[cid]:.3f} (rank {list(vec_d).index(cid) + 1})")
        if cid in bm_d:
            reasons.append(f"BM25 {bm_d[cid]:.2f} (rank {list(bm_d).index(cid) + 1})")
        elif cid in bm_raw_d:
            reasons.append(f"BM25(topic) {bm_raw_d[cid]:.2f}")
        cands.append(RetrievedChunk(chunk=ch, scores={"vector": vec_d.get(cid, 0.0), "bm25": bm_d.get(cid, bm_raw_d.get(cid, 0.0)), "rrf": score}, reasons=reasons))
    cands.sort(key=lambda c: -c.scores["rrf"])
    cands = cands[: settings.rerank_k]

    t = time.perf_counter()
    if expand and cands:
        cands = expand_graph(store, plan, cands, filters)
    lat["graph"] = (time.perf_counter() - t) * 1000

    t = time.perf_counter()
    cands = rerank(plan, cands, use_cross_encoder=settings.use_cross_encoder if use_reranker is None else use_reranker, qtext=qtext)
    lat["rerank"] = (time.perf_counter() - t) * 1000

    context = cands[:k_context]
    attach_parents(store, context)
    conflicts = detect_conflicts(context, plan)
    confidence = context[0].scores.get("final", 0.0) if context else 0.0
    top = context[0] if context else None
    sufficient = bool(top) and confidence >= settings.min_relevance and not top.scores.get("hard_demotion") and (
        top.scores.get("cross", 0.0) >= 0.5 or (top.scores.get("tax", 0.0) >= 0.45 and top.scores.get("bm25", 0.0) > 0))
    if context and not sufficient:
        relaxations.append("Top passage did not clear the relevance threshold; treated as insufficient evidence.")
    lat["total"] = (time.perf_counter() - t0) * 1000
    return RetrievalResult(plan=plan, candidates=cands, context=context, conflicts=conflicts, confidence=round(confidence, 4),
                           sufficient=sufficient, relaxations=relaxations, latency_ms={k: round(v, 1) for k, v in lat.items()},
                           filters_used={k: v for k, v in filters.items() if v is not None})
