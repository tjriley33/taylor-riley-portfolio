"""Detect potentially conflicting authority among context chunks. Never resolves; explains."""
from __future__ import annotations

from itertools import combinations

from ..models import RetrievedChunk
from .query import QueryPlan


def detect_conflicts(context: list[RetrievedChunk], plan: QueryPlan) -> list[dict]:
    out: list[dict] = []
    top = context[:6]
    for a, b in combinations(top, 2):
        ca, cb = a.chunk, b.chunk
        same_topic = _topic_overlap(ca, cb)
        if not same_topic:
            continue
        reasons = []
        if ca["jurisdiction"] != cb["jurisdiction"]:
            reasons.append(("federal_vs_state" if "US" in (ca["jurisdiction"], cb["jurisdiction"]) else "different_states",
                            f"{ca['jurisdiction']} vs {cb['jurisdiction']}: state rules may modify or decouple from federal treatment."))
        if ca["tax_year"] and cb["tax_year"] and ca["tax_year"] != cb["tax_year"]:
            reasons.append(("different_tax_years", f"tax year {ca['tax_year']} vs {cb['tax_year']}: thresholds and rules change year to year."))
        if ca["draft_or_final"] != cb["draft_or_final"]:
            reasons.append(("draft_vs_final", "one passage is from a DRAFT; drafts are not authority until released."))
        if ca["version_id"] != cb["version_id"] and ca["document_id"] == cb["document_id"] and ca["tax_year"] == cb["tax_year"]:
            reasons.append(("superseding_revision", "two revisions of the same document for the same year; the superseded one may be outdated."))
        kinds = {ca["document_type"], cb["document_type"]}
        if kinds == {"publication", "instructions"} or kinds == {"publication", "schedule_instructions"}:
            reasons.append(("publication_vs_instructions", "a general publication and a form-specific instruction both apply; form instructions are the more specific authority."))
        for code, why in reasons:
            out.append({"type": code, "explanation": why, "chunk_ids": [ca["chunk_id"], cb["chunk_id"]],
                        "sources": [_label(ca), _label(cb)]})
    return out


def _label(ch: dict) -> str:
    return f"{ch['jurisdiction']} {ch.get('tax_year') or ''} {ch['document_type']} {ch.get('form_number') or ch.get('publication_number') or ''} [{ch['draft_or_final']}] {ch['path_text'].split(' > ')[-1]}"


def _topic_overlap(a: dict, b: dict) -> bool:
    ia, ib = set(a.get("identifiers", "").split()), set(b.get("identifiers", "").split())
    ia = {i for i in ia if not i.startswith("jur_")}
    ib = {i for i in ib if not i.startswith("jur_")}
    if ia & ib:
        return True
    la, lb = a["path_text"].split(" > ")[-1].lower(), b["path_text"].split(" > ")[-1].lower()
    return la == lb or (a.get("line_refs") and set(a["line_refs"]) & set(b.get("line_refs") or []))
