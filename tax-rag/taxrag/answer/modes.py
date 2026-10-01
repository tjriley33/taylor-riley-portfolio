"""Answer modes: research | taxdev | source | compare | evidence.

All modes return structured JSON. Only research/taxdev/compare call the LLM, and
only when one is configured; otherwise they return an extractive answer that is
clearly labelled as such.
"""
from __future__ import annotations

import re
import time
import uuid
from typing import Any

from ..config import settings
from ..models import Citation, Claim, RetrievedChunk, utcnow
from ..retrieve import parse_query, retrieve
from ..retrieve.query import QueryPlan
from ..store import Store
from . import llm
from .citations import build_citation, stable_citation_id
from .prompts import COMPARE_SUFFIX, SYSTEM, TAXDEV_SUFFIX
from .validate import content_terms, strip_unsupported_from_summary, validate_claims

MODES = ("research", "taxdev", "source", "compare", "evidence")


def run_mode(store: Store, question: str, mode: str = "research", jurisdiction: str | None = None, tax_year: int | None = None,
             tax_type: str | None = None, document_types: list[str] | None = None, draft_filter: str | None = None,
             k: int | None = None, strategy: str | None = None, include_internal: bool = False, use_llm: bool | None = None) -> dict:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    t0 = time.perf_counter()
    query_id = "q_" + uuid.uuid4().hex[:12]
    plan = parse_query(question, jurisdiction=jurisdiction, tax_year=tax_year, tax_type=tax_type, document_types=document_types,
                       draft_filter=draft_filter, mode=mode)
    if include_internal:
        plan.hard_filters.pop("provenance_class", None)
        plan.notes.append("INTERNAL_TAXDEV knowledge included; internal passages are labelled and are not authority.")

    if mode == "compare" or (plan.compare_intent and mode in ("taxdev",)):
        out = _compare(store, plan, query_id, k=k, strategy=strategy, use_llm=use_llm, mode=mode)
    else:
        res = retrieve(store, plan, strategy=strategy, k_context=k)
        citations, chunks = _citations_for(store, res.context)
        out = {
            "query_id": query_id, "mode": mode, "question": question, "parsed": plan.model_dump(),
            "filters_used": res.filters_used, "relaxations": res.relaxations, "confidence": res.confidence,
            "sufficient_evidence": res.sufficient, "conflicts": res.conflicts,
            "evidence": _evidence(res.context, citations),
            "citations": [c.model_dump() | {"rendered": c.render()} for c in citations.values()],
            "retrieval_debug": _debug(res),
            "latency_ms": res.latency_ms,
        }
        if mode == "source":
            out["answer"] = None
        elif mode == "evidence":
            out["answer"] = None
            out["llm_input"] = {"system": SYSTEM, "user": _user_prompt(plan, res.context, citations)} if res.sufficient else None
        else:
            out["answer"] = _answer(plan, res.context, citations, chunks, mode, use_llm, sufficient=res.sufficient)
            out["sufficient_evidence"] = res.sufficient and not out["answer"].get("insufficient", False)
    out["latency_ms"] = {**out.get("latency_ms", {}), "end_to_end": round((time.perf_counter() - t0) * 1000, 1)}
    _log(store, out, plan)
    return out


# ------------------------------------------------------------------ helpers
def _citations_for(store: Store, context: list[RetrievedChunk]) -> tuple[dict[str, Citation], dict[str, dict]]:
    cits: dict[str, Citation] = {}
    chunks: dict[str, dict] = {}
    for i, rc in enumerate(context, start=1):
        c = build_citation(store, rc.chunk, i)
        cits[c.citation_id] = c
        chunks[rc.chunk["chunk_id"]] = rc.chunk
    return cits, chunks


def _evidence(context: list[RetrievedChunk], citations: dict[str, Citation]) -> list[dict]:
    out = []
    for i, rc in enumerate(context, start=1):
        ch = rc.chunk
        out.append({
            "citation_id": f"C{i}", "chunk_id": ch["chunk_id"], "version_id": ch["version_id"], "document_id": ch["document_id"],
            "jurisdiction": ch["jurisdiction"], "tax_year": ch["tax_year"], "draft_or_final": ch["draft_or_final"],
            "version_status": ch["version_status"], "document_type": ch["document_type"], "form_number": ch.get("form_number"),
            "schedule": ch.get("schedule"), "publication_number": ch.get("publication_number"), "path_text": ch["path_text"],
            "kind": ch["kind"], "page_start": ch["page_start"], "page_end": ch["page_end"], "line_refs": ch.get("line_refs"),
            "text": ch["text"], "parent_text": ch.get("parent_text"), "scores": rc.scores, "reasons": rc.reasons, "via": rc.via,
            "provenance_class": ch["provenance_class"], "rendered_citation": citations[f"C{i}"].render(),
            "source_url": citations[f"C{i}"].source_url, "local_url": citations[f"C{i}"].local_url,
        })
    return out


def _debug(res) -> dict:
    return {
        "candidates": [{"chunk_id": c.chunk["chunk_id"], "path_text": c.chunk["path_text"], "jurisdiction": c.chunk["jurisdiction"],
                        "tax_year": c.chunk["tax_year"], "draft_or_final": c.chunk["draft_or_final"], "page": c.chunk["page_start"],
                        "via": c.via, "scores": c.scores, "reasons": c.reasons} for c in res.candidates],
        "fts_query": res.plan.fts_query(), "embed_model": settings.embed_model, "rerank_model": settings.rerank_model if settings.use_cross_encoder else None,
    }


def _user_prompt(plan: QueryPlan, context: list[RetrievedChunk], citations: dict[str, Citation], group_labels: dict[str, str] | None = None) -> str:
    parts = [f"QUESTION: {plan.question}", ""]
    if plan.jurisdiction or plan.tax_year or plan.tax_years:
        parts.append(f"Scope requested: jurisdiction={plan.jurisdictions or 'any'} tax_year={plan.tax_years or plan.tax_year or 'unspecified'} drafts_allowed={plan.include_drafts}")
    parts.append("EVIDENCE:")
    for i, rc in enumerate(context, start=1):
        ch = rc.chunk
        cid = f"C{i}"
        c = citations[cid]
        hdr = f"[{cid}] {c.render()} | {ch['jurisdiction']} | {ch['document_type']} | status={ch['version_status']} | {ch['draft_or_final'].upper()}"
        if group_labels and ch["chunk_id"] in group_labels:
            hdr = f"[{cid}] (version {group_labels[ch['chunk_id']]}) " + hdr[len(f"[{cid}] "):]
        if ch["provenance_class"] != "PUBLIC_AUTHORITY":
            hdr = f"[{cid}] INTERNAL KNOWLEDGE (NOT AUTHORITY) | " + hdr[len(f"[{cid}] "):]
        parts.append(hdr)
        parts.append(f"Section: {ch['path_text']}")
        parts.append(ch["text"][:3000])
        if ch.get("parent_text") and ch["parent_text"] not in ch["text"]:
            parts.append(f"(Enclosing section context: {ch['parent_text'][:1200]})")
        parts.append("")
    return "\n".join(parts)


def _answer(plan: QueryPlan, context: list[RetrievedChunk], citations: dict[str, Citation], chunks: dict[str, dict], mode: str,
            use_llm: bool | None, group_labels: dict[str, str] | None = None, sufficient: bool = True) -> dict:
    if not context or not sufficient:
        return {"generated_by": "none", "insufficient": True, "summary": "Insufficient authoritative evidence was retrieved to answer this question. No answer is given from general knowledge.",
                "claims": [], "gaps": "No passage cleared the relevance threshold for the requested jurisdiction/year/document.", "model": None}
    want_llm = llm.available() if use_llm is None else (use_llm and llm.available())
    if want_llm:
        system = SYSTEM + (TAXDEV_SUFFIX if mode == "taxdev" else "") + (COMPARE_SUFFIX if group_labels else "")
        user = _user_prompt(plan, context, citations, group_labels)
        try:
            resp = llm.generate(system, user)
        except Exception as e:  # noqa: BLE001
            resp = None
            llm_error = str(e)
        else:
            llm_error = None
        if resp:
            data = llm.parse_json(resp["text"]) or {}
            claims, problems = validate_claims(data.get("claims", []), citations, chunks, plan)
            valid_ids = {c for cl in claims if cl.label != "not_established" for c in cl.citation_ids}
            summary = strip_unsupported_from_summary(data.get("answer_summary", ""), valid_ids)
            insufficient = bool(data.get("insufficient")) or not any(cl.label != "not_established" for cl in claims)
            return {"generated_by": "llm", "model": resp["model"], "usage": resp["usage"], "insufficient": insufficient,
                    "summary": summary, "claims": [c.model_dump() for c in claims], "gaps": data.get("gaps", ""),
                    "validation_problems": problems, "raw": resp["text"] if problems else None}
        fallback_note = f"LLM call failed ({llm_error}); extractive answer shown." if llm_error else None
    else:
        fallback_note = "No LLM configured (set ANTHROPIC_API_KEY). Extractive answer: verbatim passages, no synthesis."
    return _extractive(plan, context, citations, fallback_note)


def _extractive(plan: QueryPlan, context: list[RetrievedChunk], citations: dict[str, Citation], note: str | None) -> dict:
    terms = content_terms(plan.topic or plan.question)
    claims: list[dict] = []
    seen_quotes: set[str] = set()
    for i, rc in enumerate(context[:5], start=1):
        text = rc.chunk["text"]
        body = text.split("\n", 1)[1] if "\n" in text and text.startswith(rc.chunk["path_text"]) else text
        sents = [x.strip() for x in re.split(r"(?<=[.;:])\s+|\n", body) if len(x.strip()) >= 40]
        if not sents:
            continue
        scored = sorted(((len(terms & content_terms(x)), len(x), j, x) for j, x in enumerate(sents)), reverse=True)
        picked = [x for sc, _, _, x in scored[:2] if sc > 0] or [max(sents, key=len)]
        quote = " ".join(picked)[:500]
        if quote in seen_quotes:
            continue
        seen_quotes.add(quote)
        citations[f"C{i}"].quote = quote
        claims.append(Claim(text=quote, citation_ids=[f"C{i}"], label="explicit", validation=["verbatim extract"]).model_dump())
    summary = " ".join(f"{c['text']} [{c['citation_ids'][0]}]" for c in claims[:3])
    return {"generated_by": "extractive", "model": None, "insufficient": False, "summary": summary, "claims": claims,
            "gaps": "", "note": note}


def _compare(store: Store, plan: QueryPlan, query_id: str, k: int | None, strategy: str | None, use_llm: bool | None, mode: str) -> dict:
    """Retrieve deliberately for two versions (years / draft-vs-final) and attach stored section diffs."""
    years = plan.tax_years or ([plan.tax_year - 1, plan.tax_year] if plan.tax_year else [settings.current_tax_year - 1, settings.current_tax_year])
    years = sorted(years)
    sides: list[dict] = []
    all_context: list[RetrievedChunk] = []
    labels: dict[str, str] = {}
    half = max(3, (k or settings.context_k) // 2)
    for tag, yr in zip("AB", years):
        p = plan.model_copy(deep=True)
        p.tax_year, p.tax_years, p.compare_intent = yr, [], False
        p.hard_filters = {**plan.hard_filters, "tax_year": yr}
        if tag == "B" and (plan.include_drafts or mode == "taxdev"):
            p.hard_filters.pop("draft_or_final", None)   # allow newest draft on the later side
        res = retrieve(store, p, strategy=strategy, k_context=half)
        for rc in res.context:
            labels[rc.chunk["chunk_id"]] = f"{tag}={yr}"
        sides.append({"label": tag, "tax_year": yr, "filters_used": res.filters_used, "relaxations": res.relaxations,
                      "confidence": res.confidence, "sufficient": res.sufficient, "context": res.context, "debug": _debug(res)})
        all_context.extend(res.context)
    citations, chunks = _citations_for(store, all_context)
    # stored structural diffs between the resolved versions
    changes: list[dict] = []
    va = {rc.chunk["version_id"] for rc in sides[0]["context"]}
    vb = {rc.chunk["version_id"] for rc in sides[1]["context"]}
    topic_words = [w for w in content_terms(plan.topic) if len(w) > 3]
    for old in va:
        for new in vb:
            if store.get_version(old)["document_id"] != store.get_version(new)["document_id"]:
                continue
            rows = store.changes_between(old, new)
            if plan.line:
                rows = [r for r in rows if re.search(rf"\bline {re.escape(plan.line)}\b", r["path_text"].lower())] or rows
            if topic_words:
                scored = sorted(rows, key=lambda r: -len(set(content_terms(r["path_text"] + " " + (r["summary"] or ""))) & set(topic_words)))
                rows = scored
            for r in rows[:25]:
                changes.append({**r, "old_local_url": f"/files/{old}.pdf#page={r['old_page'] or 1}", "new_local_url": f"/files/{new}.pdf#page={r['new_page'] or 1}"})
    sufficient = all(s["sufficient"] for s in sides) or bool(changes)
    answer = _answer(plan, all_context, citations, chunks, mode, use_llm, group_labels=labels, sufficient=sufficient)
    return {
        "query_id": query_id, "mode": "compare", "question": plan.question, "parsed": plan.model_dump(),
        "versions_compared": [{"label": s["label"], "tax_year": s["tax_year"], "filters_used": s["filters_used"], "relaxations": s["relaxations"],
                               "confidence": s["confidence"], "version_ids": sorted({rc.chunk["version_id"] for rc in s["context"]})} for s in sides],
        "changes": changes, "evidence": _evidence(all_context, citations),
        "citations": [c.model_dump() | {"rendered": c.render(), "side": labels.get(c.chunk_id)} for c in citations.values()],
        "answer": answer, "sufficient_evidence": sufficient, "confidence": min(s["confidence"] for s in sides) if sides else 0.0,
        "conflicts": [], "relaxations": [r for s in sides for r in s["relaxations"]],
        "retrieval_debug": {"sides": [{"label": s["label"], **s["debug"]} for s in sides]},
        "latency_ms": {},
    }


def _log(store: Store, out: dict, plan: QueryPlan) -> None:
    ans = out.get("answer") or {}
    try:
        store.log_query({
            "query_id": out["query_id"], "ts": utcnow(), "mode": out["mode"], "question": out["question"], "parsed": plan.model_dump(),
            "filters": out.get("filters_used") or {"compare": out.get("versions_compared")},
            "candidates": out.get("retrieval_debug", {}).get("candidates") or out.get("retrieval_debug"),
            "context_chunk_ids": [e["chunk_id"] for e in out.get("evidence", [])],
            "citations": [c.get("rendered") for c in out.get("citations", [])], "answer": ans, "latency_ms": out.get("latency_ms"),
            "model": ans.get("model"), "embed_model": settings.embed_model, "tokens": ans.get("usage") or {},
            "confidence": out.get("confidence"), "failure": None if out.get("sufficient_evidence") else "insufficient_evidence",
        })
        store.save_citations(out["query_id"], [{"citation_id": stable_citation_id(out["query_id"], c["chunk_id"]), "chunk_id": c["chunk_id"],
                                                 "version_id": c["version_id"], "page": c["page"], "line_ref": c.get("line_ref"), "quote": c.get("quote"),
                                                 "label": None, "validated": True} for c in out.get("citations", [])])
    except Exception as e:  # noqa: BLE001
        out.setdefault("warnings", []).append(f"query log failed: {e}")
