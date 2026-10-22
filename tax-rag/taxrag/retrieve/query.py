"""Query understanding: natural language -> structured QueryPlan (filters, boosts, intent)."""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field

from ..config import settings

STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO", "connecticut": "CT",
    "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC",
}
STATE_ABBR = set(STATES.values())
STATE_FORM_HINTS = {"IT-201": "NY", "IT-225": "NY", "IT-201-ATT": "NY", "760": "VA", "760PY": "VA", "763": "VA"}

YEAR_RE = re.compile(r"\b(20[12]\d)\b")
TY_RE = re.compile(r"\b(?:TY|tax year)\s*(20[12]\d|\d{2})\b", re.I)
FORM_RE = re.compile(r"\bForm\s+((?:IT-)?\d{3,5}(?:-[A-Z]{1,3})?(?:[A-Z]{1,2})?|\d{1,2})\b", re.I)
IT_RE = re.compile(r"\b(IT-\d{3}(?:-[A-Z]+)?)\b", re.I)
SCHED_RE = re.compile(r"\bSch(?:edule|\.)?\s+([A-Z]{1,2}(?:-\d)?|\d{1,4}|K-1|SE|EIC|ADJ|CR|I)\b", re.I)
LINE_RE = re.compile(r"\b[Ll]ines?\s+(\d{1,3}[a-z]?)\b")
PUB_RE = re.compile(r"\bPub(?:lication|\.)?\s+(\d{2,4}(?:-[A-Z])?)\b", re.I)
TAXTYPE_RE = re.compile(r"\b(1040|1065|1120-?S|1120|1041|990)\b")
BETWEEN_RE = re.compile(r"\bbetween\s+(20[12]\d)\s+and\s+(20[12]\d)\b", re.I)
VS_RE = re.compile(r"\b(20[12]\d)\s+(?:vs\.?|versus|compared (?:with|to)|and)\s+(20[12]\d)\b", re.I)
CHANGE_WORDS = re.compile(r"\b(chang|differ|compar|new in|introduc|added|removed|prior[- ]year|last year|previous (?:year|version)|revision|updated)", re.I)
DRAFT_WORDS = re.compile(r"\bdraft", re.I)
DOC_TYPE_WORDS = [
    (re.compile(r"\binstructions?\b", re.I), "instructions"),
    (re.compile(r"\bpublication|\bpub\.?\b", re.I), "publication"),
    (re.compile(r"\bworksheet\b", re.I), "worksheet"),
    (re.compile(r"\bbusiness rules?\b|\bschema\b|\be-?file\b|\bMeF\b", re.I), "efile_spec"),
    (re.compile(r"\bform\b", re.I), "form"),
]
STOP = set("what is are the a an of for in on to do does did how when where which who with my i me from by at as and or be can should must".split())


class QueryPlan(BaseModel):
    question: str
    jurisdiction: Optional[str] = None            # US | VA | NY | ...
    jurisdictions: list[str] = Field(default_factory=list)  # for compare / federal-state interplay
    tax_year: Optional[int] = None
    tax_years: list[int] = Field(default_factory=list)       # compare mode
    tax_type: Optional[str] = None
    form: Optional[str] = None
    schedule: Optional[str] = None
    line: Optional[str] = None
    publication: Optional[str] = None
    document_type: Optional[str] = None
    include_drafts: bool = False
    drafts_only: bool = False
    compare_intent: bool = False
    temporal_intent: bool = False
    topic: str = ""
    identifiers: list[str] = Field(default_factory=list)
    hard_filters: dict = Field(default_factory=dict)
    soft_boosts: dict = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    def fts_query(self) -> str:
        """FTS5 MATCH expression: identifier phrases OR'd with topic terms."""
        terms = []
        for ident in self.identifiers:
            terms.append(f'identifiers:"{ident}"')
        words = [w for w in re.findall(r"[A-Za-z0-9\-]{2,}", self.topic.lower()) if w not in STOP]
        for w in words[:12]:
            terms.append(f'"{w}"')
        if self.line:
            terms.append(f'"line {self.line}"')
        return " OR ".join(terms) if terms else '"tax"'


def parse_query(question: str, jurisdiction: str | None = None, tax_year: int | None = None, tax_type: str | None = None,
                document_types: list[str] | None = None, draft_filter: str | None = None, mode: str = "research") -> QueryPlan:
    q = question.strip()
    plan = QueryPlan(question=q)
    low = q.lower()

    # jurisdiction(s)
    jurs: list[str] = []
    if re.search(r"\bfederal\b|\birs\b", low):
        jurs.append("US")
    for name, ab in STATES.items():
        if re.search(rf"\b{re.escape(name)}\b", low):
            jurs.append(ab)
    for ab in re.findall(r"\b([A-Z]{2})\b", q):
        if ab in STATE_ABBR and ab not in jurs and ab not in {"IT", "US", "IN", "OR", "ME", "OK", "HI", "ID"}:
            jurs.append(ab)
    # forms
    itm = IT_RE.search(q)
    if itm:
        plan.form = itm.group(1).upper()
        if "NY" not in jurs:
            jurs.append("NY")
    fm = FORM_RE.search(q)
    if fm and not plan.form:
        plan.form = fm.group(1).upper().replace("1120S", "1120-S")
        hint = STATE_FORM_HINTS.get(plan.form)
        if hint and hint not in jurs:
            jurs.append(hint)
    sm = SCHED_RE.search(q)
    if sm:
        plan.schedule = sm.group(1).upper()
    pm = PUB_RE.search(q)
    if pm:
        plan.publication = pm.group(1).upper()
    lm = LINE_RE.search(q)
    if lm:
        plan.line = lm.group(1)
    tm = TAXTYPE_RE.search(q)
    if tm:
        plan.tax_type = tm.group(1).upper().replace("1120S", "1120S").replace("1120-S", "1120S")
    if tax_type:
        plan.tax_type = tax_type

    if jurisdiction:
        jurs = [jurisdiction.upper()] + [j for j in jurs if j != jurisdiction.upper()]
    if not jurs and plan.form and re.match(r"^\d{3,5}", plan.form) and plan.form not in STATE_FORM_HINTS:
        jurs = ["US"]
    if not jurs and (plan.publication or plan.tax_type):
        jurs = ["US"]
    plan.jurisdictions = list(dict.fromkeys(jurs))
    plan.jurisdiction = plan.jurisdictions[0] if plan.jurisdictions else None

    # years
    years = [int(y) for y in TY_RE.findall(q) if len(y) == 4] + [int(y) for y in YEAR_RE.findall(q)]
    years = list(dict.fromkeys(years))
    bm = BETWEEN_RE.search(q) or VS_RE.search(q)
    if bm:
        plan.tax_years = [int(bm.group(1)), int(bm.group(2))]
        plan.compare_intent = True
    elif len(years) >= 2 and CHANGE_WORDS.search(low):
        plan.tax_years = years[:2]
        plan.compare_intent = True
    if tax_year:
        plan.tax_year = tax_year
    elif years:
        plan.tax_year = years[0]
    elif re.search(r"\bcurrent\b|\bthis year\b|\blatest\b", low):
        plan.tax_year = settings.current_tax_year
        plan.notes.append(f"'current' resolved to tax year {settings.current_tax_year}")
    if re.search(r"\blast year\b|\bprior year\b|\bprevious year\b", low) and not plan.tax_years:
        base = plan.tax_year or settings.current_tax_year
        plan.tax_years = [base - 1, base]
        plan.compare_intent = bool(CHANGE_WORDS.search(low))
        plan.temporal_intent = True
    if CHANGE_WORDS.search(low):
        plan.temporal_intent = True

    # draft handling
    if DRAFT_WORDS.search(low) or draft_filter == "draft" or mode == "taxdev":
        plan.include_drafts = True
    if draft_filter == "draft":
        plan.drafts_only = True
    if draft_filter == "final":
        plan.include_drafts = False

    # document type
    if document_types:
        plan.document_type = document_types[0] if len(document_types) == 1 else None
    else:
        # "Form 1065" / "Schedule C" are identifiers, not a request for the form itself: strip them before type inference
        low_wo_ids = IT_RE.sub(" ", FORM_RE.sub(" ", SCHED_RE.sub(" ", q))).lower()
        for rx, dt in DOC_TYPE_WORDS:
            if rx.search(low_wo_ids):
                plan.document_type = dt
                break
        if plan.schedule and plan.document_type == "instructions":
            plan.document_type = "schedule_instructions"
        elif plan.schedule and plan.document_type == "form":
            plan.document_type = "schedule"

    # identifiers for lexical boosting
    ids = []
    if plan.form:
        ids.append(f"form_{plan.form.lower()}")
    if plan.schedule:
        ids.append(f"sched_{plan.schedule.lower()}")
    if plan.publication:
        ids.append(f"pub_{plan.publication.lower()}")
    if plan.line:
        ids.append(f"line_{plan.line.lower()}")
    plan.identifiers = ids

    # topic = question minus identifiers / years / jurisdiction words
    topic = q
    for rx in (FORM_RE, IT_RE, SCHED_RE, LINE_RE, PUB_RE, YEAR_RE, TY_RE):
        topic = rx.sub(" ", topic)
    for name in STATES:
        topic = re.sub(rf"\b{name}\b", " ", topic, flags=re.I)
    topic = re.sub(r"\b(federal|irs|instructions?|form|publication|draft|final|what|does|say|about)\b", " ", topic, flags=re.I)
    plan.topic = re.sub(r"\s+", " ", topic).strip() or q

    # filters
    hard: dict = {"provenance_class": "PUBLIC_AUTHORITY"}
    if plan.jurisdiction and not (len(plan.jurisdictions) > 1):
        hard["jurisdiction"] = plan.jurisdiction
    elif plan.jurisdictions:
        hard["jurisdiction"] = plan.jurisdictions
    if plan.tax_year and not plan.tax_years:
        hard["tax_year"] = plan.tax_year
    if plan.tax_years:
        hard["tax_year"] = plan.tax_years
    if plan.drafts_only:
        hard["draft_or_final"] = "draft"
    elif not plan.include_drafts:
        hard["draft_or_final"] = "final"
    if document_types and len(document_types) > 1:
        hard["document_type"] = document_types
    plan.hard_filters = hard
    soft = {}
    if plan.form:
        soft["form_number"] = plan.form
    if plan.schedule:
        soft["schedule"] = plan.schedule
    if plan.publication:
        soft["publication_number"] = plan.publication
    if plan.document_type:
        soft["document_type"] = plan.document_type
    if plan.tax_type:
        soft["tax_type"] = plan.tax_type
    plan.soft_boosts = soft
    return plan
