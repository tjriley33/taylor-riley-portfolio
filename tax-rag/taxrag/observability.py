"""Observability helpers: a compact per-query debug view explaining why each chunk was retrieved."""
from __future__ import annotations

from .store import Store


def debug_view(store: Store, query_id: str) -> dict:
    q = store.get_query(query_id)
    if not q:
        return {}
    cands = q.get("candidates") or []
    if isinstance(cands, dict):
        cands = [c for side in cands.get("sides", []) for c in side.get("candidates", [])]
    ctx = set(q.get("context_chunk_ids") or [])
    return {
        "query_id": query_id, "question": q["question"], "mode": q["mode"], "parsed": q.get("parsed"), "filters": q.get("filters"),
        "latency_ms": q.get("latency_ms"), "model": q.get("model"), "embed_model": q.get("embed_model"), "tokens": q.get("tokens"),
        "confidence": q.get("confidence"), "failure": q.get("failure"), "feedback": q.get("feedback"),
        "why": [{"chunk_id": c["chunk_id"], "in_context": c["chunk_id"] in ctx, "path": c.get("path_text"), "jurisdiction": c.get("jurisdiction"),
                 "tax_year": c.get("tax_year"), "page": c.get("page"), "via": c.get("via"), "scores": c.get("scores"), "reasons": c.get("reasons")}
                for c in cands],
        "citations": q.get("citations"),
    }
