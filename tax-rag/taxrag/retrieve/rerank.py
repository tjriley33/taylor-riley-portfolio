"""Rerank candidates: cross-encoder relevance + deterministic tax-aware scoring.

The tax score is not a soft tie-breaker: when the user named a jurisdiction, year,
form or line, a mismatching passage is demoted hard so a fluent passage from the
wrong state/year cannot outrank the right authority.
"""
from __future__ import annotations

import math
import re

from ..models import AUTHORITY_WEIGHT, DocumentType, RetrievedChunk
from .query import QueryPlan


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def tax_score(plan: QueryPlan, ch: dict, via: str) -> tuple[float, list[str], bool]:
    s, why, hard = 0.0, [], False
    form = (ch.get("form_number") or "").upper()
    ids = set((ch.get("identifiers") or "").split())
    path = (ch.get("path_text") or "").lower()

    if plan.form:
        pf = plan.form.upper()
        if form == pf:
            s += 0.25; why.append("exact form match")
        elif f"form_{pf.lower()}" in ids:
            s += 0.10; why.append("form mentioned")
        else:
            s -= 0.15; why.append("different form")
    if plan.schedule:
        ps = plan.schedule.upper()
        if (ch.get("schedule") or "").upper() == ps:
            s += 0.15; why.append("exact schedule match")
        elif f"sched_{ps.lower()}" in ids or f"schedule {ps.lower()}" in path:
            s += 0.08; why.append("schedule mentioned")
        else:
            s -= 0.10
    if plan.publication:
        if (ch.get("publication_number") or "").upper() == plan.publication.upper():
            s += 0.2; why.append("exact publication match")
    if plan.line:
        ln = plan.line.lower()
        if re.search(rf"\bline {re.escape(ln)}\b", path):
            s += 0.30; why.append(f"section is Line {plan.line}")
        elif ln in [str(x).lower() for x in ch.get("line_refs") or []]:
            s += 0.12; why.append(f"mentions line {plan.line}")
        else:
            s -= 0.05
    if plan.jurisdiction:
        if ch.get("jurisdiction") == plan.jurisdiction or ch.get("jurisdiction") in plan.jurisdictions:
            s += 0.10; why.append("jurisdiction match")
        else:
            s -= 0.40; hard = True; why.append(f"WRONG JURISDICTION ({ch.get('jurisdiction')})")
    if plan.tax_year or plan.tax_years:
        years = plan.tax_years or [plan.tax_year]
        if ch.get("tax_year") in years:
            s += 0.10; why.append("tax-year match")
        elif ch.get("tax_year") is None:
            s += 0.0; why.append("continuous-use document (no tax year)")
        else:
            s -= 0.35; hard = True; why.append(f"WRONG TAX YEAR ({ch.get('tax_year')})")
    if plan.document_type:
        if ch.get("document_type") == plan.document_type:
            s += 0.10; why.append("document-type match")
    if ch.get("draft_or_final") == "final":
        s += 0.05
    else:
        why.append("DRAFT")
        if not plan.include_drafts:
            s -= 0.2
    if ch.get("version_status") != "current":
        s -= 0.15; why.append("superseded version")
    try:
        s += 0.10 * AUTHORITY_WEIGHT.get(DocumentType(ch.get("document_type")), 0.5)
    except ValueError:
        pass
    if via == "graph":
        s -= 0.05; why.append("reached via cross-reference")
    if ch.get("kind") in ("caution", "tip", "example", "worksheet"):
        why.append(ch["kind"].upper())
    return s, why, hard


def rerank(plan: QueryPlan, cands: list[RetrievedChunk], use_cross_encoder: bool = True, qtext: str | None = None) -> list[RetrievedChunk]:
    if not cands:
        return cands
    cross = [0.0] * len(cands)
    if use_cross_encoder:
        try:
            from ..embed import cross_scores
            passages = [(c.chunk["path_text"].split(" > ")[-1] + ": " + c.chunk["text"])[:1200] for c in cands]
            cross = cross_scores(qtext or plan.question, passages)
        except Exception as e:  # noqa: BLE001
            for c in cands:
                c.reasons.append(f"cross-encoder unavailable: {e}")
    rrf_max = max(c.scores.get("rrf", 0.0) for c in cands) or 1.0
    for c, ce in zip(cands, cross):
        ts, why, hard = tax_score(plan, c.chunk, c.via)
        ce_n = _sig(ce) if use_cross_encoder else 0.0
        rrf_n = c.scores.get("rrf", 0.0) / rrf_max
        final = (0.5 * ce_n if use_cross_encoder else 0.0) + (0.3 if use_cross_encoder else 0.8) * rrf_n + ts
        if hard:
            final *= 0.3   # a wrong-state / wrong-year passage can never outrank a correct one on fluency
        c.scores.update({"cross": round(ce_n, 4), "tax": round(ts, 4), "final": round(final, 4), "hard_demotion": 1.0 if hard else 0.0})
        c.reasons.extend(why)
    cands.sort(key=lambda c: -c.scores["final"])
    return cands
