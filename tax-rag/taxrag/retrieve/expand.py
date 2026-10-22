"""Relationship expansion (follow explicit cross-references) and parent-section expansion."""
from __future__ import annotations

from ..config import settings
from ..models import RetrievedChunk
from ..store import Store
from .query import QueryPlan


def expand_graph(store: Store, plan: QueryPlan, cands: list[RetrievedChunk], filters: dict, top_n: int = 8, per_edge: int = 2) -> list[RetrievedChunk]:
    """For the top candidates, follow references_* edges to target documents and pull the target's
    best-matching chunks (lexical match on the topic within that document, same year filter)."""
    have = {c.chunk["chunk_id"] for c in cands}
    rels = store.relationships_from([c.chunk["chunk_id"] for c in cands[:top_n]])
    added: list[RetrievedChunk] = []
    seen_targets: set[str] = set()
    for r in rels:
        if not r["dst_id"] or r["dst_id"] in seen_targets or r["rel_type"] in ("references_irc", "references_reg", "references_worksheet"):
            continue
        seen_targets.add(r["dst_id"])
        f = {k: v for k, v in filters.items() if k in ("strategy", "draft_or_final", "provenance_class", "tax_year")}
        f["document_id"] = r["dst_id"]
        if f.get("tax_year") and store.count_chunks(f) == 0:
            f.pop("tax_year")
        q = plan.fts_query()
        if plan.line and "references_line" == r["rel_type"]:
            q = f'"line {plan.line}" OR ' + q
        hits = store.fts_search(q, f, k=per_edge)
        rows = store.get_chunks([h[0] for h in hits])
        for cid, score in hits:
            if cid in have or cid not in rows:
                continue
            have.add(cid)
            src = next((c for c in cands if c.chunk["chunk_id"] == r["src_id"]), None)
            added.append(RetrievedChunk(chunk=rows[cid], via="graph",
                                        scores={"bm25": score, "rrf": (src.scores.get("rrf", 0.0) * 0.6) if src else 0.005},
                                        reasons=[f"followed '{r['rel_type']}' -> {r['dst_label']} from {src.chunk['path_text'].split(' > ')[-1] if src else r['src_id'][:8]}"]))
        if len(added) >= 10:
            break
    return cands + added


def attach_parents(store: Store, context: list[RetrievedChunk], max_chars: int = 2500) -> None:
    """Attach the enclosing section text (bounded) so the LLM sees authoritative context while the citation stays precise."""
    for c in context:
        ch = c.chunk
        parent_text = None
        if ch.get("parent_chunk_id"):
            p = store.get_chunk(ch["parent_chunk_id"])
            if p:
                parent_text = p["text"]
        if parent_text is None and ch.get("section_id"):
            sec = store.get_section(ch["section_id"])
            if sec and sec["text"] and sec["text"] != ch["text"]:
                parent_text = sec["text"]
        if parent_text:
            c.chunk["parent_text"] = parent_text[:max_chars]
