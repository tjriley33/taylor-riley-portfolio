"""Citation + claim validation. Nothing reaches the user as 'supported' unless it passes here."""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from ..models import Citation, Claim
from ..retrieve.query import QueryPlan, STOP

WORD = re.compile(r"[a-z0-9][a-z0-9\-\.]+")


def content_terms(text: str) -> set[str]:
    return {w for w in WORD.findall(text.lower()) if w not in STOP and len(w) > 2}


def validate_claims(raw_claims: list[dict], citations: dict[str, Citation], chunks: dict[str, dict], plan: QueryPlan) -> tuple[list[Claim], list[str]]:
    claims: list[Claim] = []
    problems: list[str] = []
    for rc in raw_claims or []:
        text = (rc.get("text") or "").strip()
        if not text:
            continue
        cids = [c for c in (rc.get("citations") or []) if isinstance(c, str)]
        valid = [c for c in cids if c in citations]
        notes = []
        for c in cids:
            if c not in citations:
                notes.append(f"manufactured citation {c} dropped")
                problems.append(f"claim cited unknown passage {c}")
        label = rc.get("label", "derived")
        quote = (rc.get("quote") or "").strip()
        if not valid:
            claims.append(Claim(text=text, citation_ids=[], label="not_established", validation=notes + ["no valid citation"]))
            continue
        texts = [chunks[citations[c].chunk_id]["text"] + " " + (chunks[citations[c].chunk_id].get("parent_text") or "") for c in valid]
        quote_ok = False
        if quote:
            quote_ok = any(fuzz.partial_ratio(quote.lower(), t.lower()) >= 85 for t in texts)
            if not quote_ok:
                notes.append("quote not found in cited passage")
        overlap = max((len(content_terms(text) & content_terms(t)) for t in texts), default=0)
        if label == "explicit" and quote_ok:
            final = "explicit"
        elif overlap >= 3 or quote_ok:
            final = "derived" if not quote_ok else "explicit"
            if label == "explicit" and not quote_ok:
                notes.append("downgraded to derived: quote unverifiable")
        else:
            final = "not_established"
            notes.append("claim terms not found in cited passages")
        # jurisdiction / year / version checks against the plan
        for c in valid:
            ct = citations[c]
            if plan.jurisdiction and ct.jurisdiction not in plan.jurisdictions:
                notes.append(f"{c} is {ct.jurisdiction}, question asked about {plan.jurisdiction}")
            years = plan.tax_years or ([plan.tax_year] if plan.tax_year else [])
            if years and ct.tax_year and ct.tax_year not in years:
                notes.append(f"{c} is tax year {ct.tax_year}, question asked about {years}")
            if ct.draft_or_final != "final":
                notes.append(f"{c} is a DRAFT")
            if ct.version_status != "current":
                notes.append(f"{c} is a superseded revision")
        if quote_ok:
            for c in valid:
                if citations[c].quote is None:
                    citations[c].quote = quote[:300]
        claims.append(Claim(text=text, citation_ids=valid, label=final, validation=notes))
    return claims, problems


def strip_unsupported_from_summary(summary: str, valid_ids: set[str]) -> str:
    """Remove bracketed citation ids that did not validate; sentences left with no citation get a marker."""
    def fix(m):
        ids = [i.strip() for i in m.group(1).split(",")]
        keep = [i for i in ids if i in valid_ids]
        return f"[{', '.join(keep)}]" if keep else "[unsupported]"
    return re.sub(r"\[((?:C\d+\s*,?\s*)+)\]", fix, summary or "")
