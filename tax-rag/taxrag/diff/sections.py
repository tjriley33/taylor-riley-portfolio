"""Section-level semantic diff between two versions of the same document.

Sections are aligned by normalized path_text (exact), then by fuzzy heading match
within the same parent, then leftovers become added/removed. Modified sections get
a unified text diff plus sub-classification: line_changed (line heading sections),
table_changed (worksheet/table kinds), reference_changed (set of referenced
forms/pubs/schedules differs).
"""
from __future__ import annotations

import difflib
import re

from rapidfuzz import fuzz

from ..chunk.common import IDENT_RES

WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return WS.sub(" ", re.sub(r"[^a-z0-9 ]", "", s.lower())).strip()


def _refs(text: str) -> set[str]:
    out = set()
    for rx, fmt in IDENT_RES:
        if fmt.startswith("line_"):
            continue
        for m in rx.finditer(text):
            out.add(fmt.format(m.group(1).upper()).lower())
    return out


def _key(path_text: str) -> str:
    # drop the root (document title) so title changes don't break alignment
    parts = path_text.split(" > ")[1:]
    return _norm(" > ".join(parts))


def diff_versions(store, old_vid: str, new_vid: str, min_similarity: float = 0.985) -> list[dict]:
    old = [s for s in store.sections_for_version(old_vid) if s["text"].strip()]
    new = [s for s in store.sections_for_version(new_vid) if s["text"].strip()]
    old_by_key: dict[str, list[dict]] = {}
    for s in old:
        old_by_key.setdefault(_key(s["path_text"]), []).append(s)
    changes: list[dict] = []
    matched_old: set[str] = set()

    unmatched_new: list[dict] = []
    for s in new:
        k = _key(s["path_text"])
        cands = [o for o in old_by_key.get(k, []) if o["section_id"] not in matched_old]
        if cands:
            o = cands[0]
            matched_old.add(o["section_id"])
            _compare(o, s, changes, min_similarity)
        else:
            unmatched_new.append(s)

    # fuzzy pass: same parent path, similar heading
    remaining_old = [o for o in old if o["section_id"] not in matched_old]
    for s in unmatched_new:
        parent = _norm(" > ".join(s["path_text"].split(" > ")[1:-1]))
        best, best_score = None, 0
        for o in remaining_old:
            if _norm(" > ".join(o["path_text"].split(" > ")[1:-1])) != parent:
                continue
            sc = fuzz.ratio(_norm(s["heading"]), _norm(o["heading"]))
            if sc > best_score:
                best, best_score = o, sc
        if best is not None and best_score >= 80:
            matched_old.add(best["section_id"])
            remaining_old.remove(best)
            _compare(best, s, changes, min_similarity, renamed=True)
        else:
            changes.append({"change_type": "section_added", "new_section_id": s["section_id"], "path_text": s["path_text"],
                            "new_page": s["page_start"], "similarity": 0.0, "diff_text": None,
                            "summary": f"New section '{s['heading']}' (p. {s['page_start']})"})
    for o in remaining_old:
        changes.append({"change_type": "section_removed", "old_section_id": o["section_id"], "path_text": o["path_text"],
                        "old_page": o["page_start"], "similarity": 0.0, "diff_text": None,
                        "summary": f"Section '{o['heading']}' removed (was p. {o['page_start']})"})
    return changes


def _compare(o: dict, s: dict, changes: list[dict], min_similarity: float, renamed: bool = False) -> None:
    ot, nt = WS.sub(" ", o["text"]).strip(), WS.sub(" ", s["text"]).strip()
    if ot == nt and not renamed:
        return
    sim = difflib.SequenceMatcher(None, ot, nt, autojunk=False).ratio() if (len(ot) + len(nt)) < 60000 else fuzz.ratio(ot, nt) / 100
    if sim >= min_similarity and not renamed:
        return
    old_lines = [l for l in re.split(r"(?<=[.;:])\s+", ot) if l]
    new_lines = [l for l in re.split(r"(?<=[.;:])\s+", nt) if l]
    diff = "\n".join(difflib.unified_diff(old_lines, new_lines, fromfile=f"old p.{o['page_start']}", tofile=f"new p.{s['page_start']}", lineterm="", n=1))
    if s["kind"] in ("worksheet", "table"):
        ctype = "table_changed"
    elif s["kind"] == "line" or o["kind"] == "line":
        ctype = "line_changed"
    elif _refs(ot) != _refs(nt):
        ctype = "reference_changed"
    else:
        ctype = "section_modified"
    added = [l[1:] for l in diff.split("\n") if l.startswith("+") and not l.startswith("+++")]
    removed = [l[1:] for l in diff.split("\n") if l.startswith("-") and not l.startswith("---")]
    summary = f"{s['heading']}: {len(removed)} sentence(s) removed, {len(added)} added (similarity {sim:.2f})"
    if ctype == "reference_changed":
        summary += f"; references {sorted(_refs(ot) ^ _refs(nt))}"
    changes.append({"change_type": ctype, "old_section_id": o["section_id"], "new_section_id": s["section_id"], "path_text": s["path_text"],
                    "old_page": o["page_start"], "new_page": s["page_start"], "similarity": round(sim, 4), "diff_text": diff[:20000], "summary": summary})
    if ctype != "reference_changed" and _refs(ot) != _refs(nt):
        changes.append({"change_type": "reference_changed", "old_section_id": o["section_id"], "new_section_id": s["section_id"],
                        "path_text": s["path_text"], "old_page": o["page_start"], "new_page": s["page_start"], "similarity": round(sim, 4),
                        "diff_text": None, "summary": f"{s['heading']}: referenced documents changed {sorted(_refs(ot) ^ _refs(nt))}"})
