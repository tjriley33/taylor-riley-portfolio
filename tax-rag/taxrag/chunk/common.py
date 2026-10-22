from __future__ import annotations

import hashlib
import re

IDENT_RES = [
    (re.compile(r"\bForm\s+([A-Z]{0,2}-?\d{3,5}[A-Z]{0,3}(?:-[A-Z]{1,3})?)\b", re.I), "form_{}"),
    (re.compile(r"\bSchedules?\s+([A-Z]{1,2}(?:-\d)?|\d{1,4}|K-1|SE|EIC|8812|ADJ|CR)\b(?!\s*\()"), "sched_{}"),
    (re.compile(r"\bPub(?:lication|\.)?\s+(\d{2,4}(?:-[A-Z])?)\b", re.I), "pub_{}"),
    (re.compile(r"\b[Ll]ines?\s+(\d{1,3}[a-z]?)\b"), "line_{}"),
    (re.compile(r"\bIT-(\d{3}(?:-[A-Z]+)?)\b"), "form_it-{}"),
    (re.compile(r"\b(?:IRC|Code)?\s*[Ss]ection\s+(\d{1,4}[A-Za-z]?(?:\([a-z0-9]+\))*)"), "irc_{}"),
]


def approx_tokens(text: str) -> int:
    return max(1, int(len(text) / 4))


def chunk_id(version_id: str, strategy: str, ordinal: int, text: str) -> str:
    return "chk_" + hashlib.sha1(f"{version_id}|{strategy}|{ordinal}|{text[:80]}".encode()).hexdigest()[:16]


def identifiers_for(text: str, path_text: str = "", doc: dict | None = None) -> str:
    ids: set[str] = set()
    for rx, fmt in IDENT_RES:
        for m in rx.finditer(f"{path_text} {text}"):
            ids.add(fmt.format(m.group(1).upper().replace(" ", "")).lower())
    if doc:
        if doc.get("form_number"):
            ids.add(f"form_{doc['form_number']}".lower())
        if doc.get("schedule"):
            ids.add(f"sched_{doc['schedule']}".lower())
        if doc.get("publication_number"):
            ids.add(f"pub_{doc['publication_number']}".lower())
        if doc.get("jurisdiction"):
            ids.add(f"jur_{doc['jurisdiction']}".lower())
    return " ".join(sorted(ids))


def line_refs_in(text: str, path_text: str = "") -> list[str]:
    refs = set()
    for m in re.finditer(r"\b[Ll]ines?\s+(\d{1,3}[a-z]?)", f"{path_text} {text}"):
        refs.add(m.group(1))
    return sorted(refs)[:20]
