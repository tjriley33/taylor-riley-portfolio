"""Cross-document reference extraction -> typed relationships.

Sources of edges:
* text patterns inside chunks (Form X, Schedule X (Form Y), Pub. N, line N of Form X,
  IRC section, Regulations section, Worksheet names)
* structural: instructions_for (instructions -> form), schedule_of (schedule -> parent form)
* state -> federal conformity (state text that mentions federal forms / federal AGI)

dst_id is resolved to a document_id when the store knows the target; otherwise
left NULL with the raw label so it can be resolved later.
"""
from __future__ import annotations

import re
from typing import Iterable

from ..models import ChunkRecord, DocumentIdentity, DocumentType, Relationship

FORM_RE = re.compile(r"\bForms?\s+((?:[A-Z]{1,2}-)?\d{3,5}(?:-[A-Z]{1,3})?(?:[A-Z]{1,2})?)\b(?!\s*,\s*line)")
FORM_LINE_RE = re.compile(r"\bForm\s+((?:[A-Z]{1,2}-)?\d{3,5}(?:-[A-Z]{1,3})?),?\s+line\s+(\d{1,3}[a-z]?)", re.I)
SCHED_FORM_RE = re.compile(r"\bSchedule\s+([A-Z]{1,2}|\d{1,4}|K-1|SE|EIC|8812)\s*\(Form\s+([\w-]+)\)")
SCHED_BARE_RE = re.compile(r"\bSchedules?\s+([A-Z]{1,2}|\d{1,2}|K-1|SE|EIC|8812|ADJ|CR|OSC|INC|I|M|CS)\b(?!\s*\()")
PUB_RE = re.compile(r"\bPub(?:lication|\.)?\s+(\d{2,4}(?:-[A-Z])?)\b", re.I)
IRC_RE = re.compile(r"\b(?:section|sec\.|§)\s*(\d{1,4}[A-Za-z]?(?:\([a-zA-Z0-9]+\))*)(?:\s+of\s+the\s+Internal\s+Revenue\s+Code)?", re.I)
REG_RE = re.compile(r"\bRegulations?\s+section\s+(\d+\.\d+[\w\-\.\(\)]*)", re.I)
WORKSHEET_RE = re.compile(r"\b([A-Z][\w\s,]{3,60}?Worksheet)\b")
NY_FORM_RE = re.compile(r"\bForm\s+(IT-\d{3}(?:-[A-Z]+)?)\b")
FEDERAL_RE = re.compile(r"\bfederal\s+(adjusted\s+gross\s+income|AGI|Form\s+1040|Schedule\s+[A-Z1-9]|taxable\s+income|return)\b", re.I)

FEDERAL_DOC_TYPES = {"form": DocumentType.form, "instructions": DocumentType.instructions}


def _resolve(store, jurisdiction: str, **kw) -> str | None:
    docs = store.find_documents(jurisdiction=jurisdiction, **kw)
    if not docs:
        return None
    # prefer form over instructions when ambiguous
    docs.sort(key=lambda d: (d["document_type"] != "form", d["document_type"] != "schedule"))
    return docs[0]["document_id"]


def extract_relationships(store, chunks: Iterable[ChunkRecord], doc: dict, version: dict) -> list[Relationship]:
    rels: list[Relationship] = []
    jur = doc["jurisdiction"]
    own_form = (doc.get("form_number") or "").upper()
    own_sched = (doc.get("schedule") or "").upper()

    # structural edges
    if doc["document_type"] in ("instructions", "schedule_instructions") and own_form:
        target = _resolve(store, jur, form_number=own_form, schedule=own_sched or None,
                          document_type="schedule" if own_sched else "form")
        rels.append(Relationship(src_type="document", src_id=doc["document_id"], rel_type="instructions_for", dst_type="document",
                                 dst_id=target, dst_label=f"Form {own_form}" + (f" Schedule {own_sched}" if own_sched else ""), dst_jurisdiction=jur))
    if own_sched and doc["document_type"] in ("schedule", "schedule_instructions"):
        target = _resolve(store, jur, form_number=own_form, document_type="form")
        rels.append(Relationship(src_type="document", src_id=doc["document_id"], rel_type="schedule_of", dst_type="document",
                                 dst_id=target, dst_label=f"Form {own_form}", dst_jurisdiction=jur))

    for ch in chunks:
        text = ch.text
        seen: set[tuple[str, str]] = set()

        def add(rel_type: str, label: str, dst_id: str | None, dst_jur: str | None = None, conf: float = 0.9):
            key = (rel_type, label.upper())
            if key in seen:
                return
            seen.add(key)
            rels.append(Relationship(src_type="chunk", src_id=ch.chunk_id, rel_type=rel_type, dst_type="document", dst_id=dst_id,
                                     dst_label=label, dst_jurisdiction=dst_jur or jur, confidence=conf, evidence_page=ch.page_start))

        for m in FORM_LINE_RE.finditer(text):
            f, line = m.group(1).upper(), m.group(2)
            if f == own_form:
                continue
            tj = "US" if re.match(r"^\d", f) and jur != "US" and f in {"1040", "1040-SR", "1040-NR", "1065", "1120", "1120-S", "1041", "990"} else jur
            add("references_line", f"Form {f}, line {line}", _resolve(store, tj, form_number=f, document_type="form"), tj)
        for m in SCHED_FORM_RE.finditer(text):
            s, f = m.group(1).upper(), m.group(2).upper()
            if s == own_sched and f == own_form:
                continue
            tj = "US" if jur != "US" and f.startswith(("1040", "1065", "1120", "1041", "990")) else jur
            add("references_schedule", f"Schedule {s} (Form {f})", _resolve(store, tj, form_number=f, schedule=s, document_type="schedule"), tj)
        for m in SCHED_BARE_RE.finditer(text):
            s = m.group(1).upper()
            if s == own_sched or not own_form:
                continue
            add("references_schedule", f"Schedule {s}", _resolve(store, jur, form_number=own_form, schedule=s, document_type="schedule"), jur, 0.6)
        for m in FORM_RE.finditer(text):
            f = m.group(1).upper()
            if f == own_form or f in {"W-2", "1099"}:
                continue
            is_fed_core = f in {"1040", "1040-SR", "1040-NR", "1065", "1120", "1120-S", "1041", "990"}
            tj = "US" if (jur != "US" and is_fed_core) else jur
            add("references_form", f"Form {f}", _resolve(store, tj, form_number=f, document_type="form"), tj)
        for m in NY_FORM_RE.finditer(text):
            f = m.group(1).upper()
            if f != own_form:
                add("references_form", f"Form {f}", _resolve(store, "NY", form_number=f, document_type="form"), "NY")
        for m in PUB_RE.finditer(text):
            p = m.group(1).upper()
            if p == (doc.get("publication_number") or "").upper():
                continue
            add("references_publication", f"Publication {p}", _resolve(store, "US", publication_number=p), "US")
        for m in IRC_RE.finditer(text):
            if "Internal Revenue Code" in m.group(0) or re.search(r"\bIRC\b|\bCode\b", text[max(0, m.start() - 30):m.start()]):
                add("references_irc", f"IRC §{m.group(1)}", None, "US", 0.8)
        for m in REG_RE.finditer(text):
            add("references_reg", f"Treas. Reg. §{m.group(1)}", None, "US", 0.8)
        for m in WORKSHEET_RE.finditer(text):
            w = m.group(1).strip()
            if len(w) < 70 and w.lower() != "worksheet":
                add("references_worksheet", w, None, jur, 0.5)
        if jur != "US" and FEDERAL_RE.search(text):
            add("conforms_to_federal", "Federal Form 1040 / federal AGI", _resolve(store, "US", form_number="1040", document_type="form"), "US", 0.7)
    return rels
