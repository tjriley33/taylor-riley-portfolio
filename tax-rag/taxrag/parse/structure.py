"""Build a section hierarchy from a PdfExtraction.

Strategy:
1. If the PDF has an outline (bookmarks), use it as the authoritative skeleton:
   each entry becomes a section anchored at the first block on its page whose
   text fuzzy-matches the title.
2. Otherwise (or for blocks between anchors), use heading blocks detected by
   font size / boldness.
3. Blocks tagged tip/caution/example/worksheet/etc. become child nodes of the
   section they appear in so they can be chunked and cited independently.
"""
from __future__ import annotations

import hashlib
import re

from rapidfuzz import fuzz

from ..models import Block, SectionNode
from .pdf import PdfExtraction, LINE_HEAD_RE

SUBKINDS = {"tip", "caution", "note", "example", "exception", "worksheet", "definition", "table"}


def _sid(version_id: str, ordinal: int, heading: str) -> str:
    return "sec_" + hashlib.sha1(f"{version_id}|{ordinal}|{heading}".encode()).hexdigest()[:16]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def build_sections(ex: PdfExtraction, version_id: str, doc_title: str = "") -> list[SectionNode]:
    all_blocks: list[Block] = [b for p in ex.pages for b in p.blocks if b.kind != "footer"]
    anchors = _anchors_from_outline(ex, all_blocks) if ex.outline else {}
    root_title = doc_title or ex.metadata.get("title") or "Document"

    sections: list[SectionNode] = []
    ordinal = 0
    root = SectionNode(section_id=_sid(version_id, 0, root_title), version_id=version_id, parent_section_id=None, level=0,
                       heading=root_title, path=[root_title], page_start=1, page_end=ex.page_count, ordinal=0)
    sections.append(root)
    stack: list[SectionNode] = [root]      # stack[-1] is current section
    use_outline = bool(anchors)
    outline_level = 0                      # level of the most recent outline anchor

    def open_section(heading: str, level: int, page: int, kind: str = "section", line_ref: str | None = None) -> SectionNode:
        nonlocal ordinal
        while len(stack) > 1 and stack[-1].level >= level:
            stack.pop()
        parent = stack[-1]
        ordinal += 1
        node = SectionNode(section_id=_sid(version_id, ordinal, heading), version_id=version_id,
                           parent_section_id=parent.section_id, level=level, heading=heading,
                           path=parent.path + [heading], kind=kind, line_ref=line_ref, page_start=page, page_end=page, ordinal=ordinal)
        sections.append(node)
        stack.append(node)
        return node

    for idx, b in enumerate(all_blocks):
        if use_outline and idx in anchors:
            lvl, title = anchors[idx]
            lm = LINE_HEAD_RE.match(title)
            kind = "line" if lm else "section"
            open_section(title, lvl, b.page, kind=kind, line_ref=lm.group(1).replace(" ", "") if lm else None)
            outline_level = lvl
            continue
        if b.kind == "line_heading":
            # Outline usually has these; if not anchored, create a node one level below the current heading.
            if not (use_outline and _already_open(stack, b.text)):
                lvl = (outline_level + 2) if use_outline else max(stack[-1].level + 1, 2)
                if stack[-1].kind == "line" and stack[-1].level <= lvl:
                    lvl = stack[-1].level
                open_section(b.text, lvl, b.page, kind="line", line_ref=b.line_ref)
            continue
        if b.kind == "heading" and not use_outline:
            open_section(b.text, max(1, b.level), b.page)
            continue
        if b.kind == "heading" and use_outline:
            # Headings not in the outline become sub-sections below the current node.
            if not _already_open(stack, b.text):
                # bounded nesting: outline level + font-derived level (1..3)
                open_section(b.text, outline_level + max(1, b.level), b.page)
            continue
        cur = stack[-1]
        if b.kind in SUBKINDS:
            # Independent child node carrying its own kind; does not change the stack.
            ordinal += 1
            label = {"tip": "TIP", "caution": "CAUTION", "note": "Note", "example": "Example", "exception": "Exception",
                     "worksheet": "Worksheet", "definition": "Definition", "table": "Table"}[b.kind]
            child = SectionNode(section_id=_sid(version_id, ordinal, label + b.text[:30]), version_id=version_id,
                                parent_section_id=cur.section_id, level=cur.level + 1, heading=f"{label}: {b.text[:60]}",
                                path=cur.path + [label], kind=b.kind, line_ref=cur.line_ref, page_start=b.page, page_end=b.page,
                                ordinal=ordinal, text=b.text, blocks=[b])
            sections.append(child)
            cur.page_end = max(cur.page_end, b.page)
            continue
        cur.blocks.append(b)
        cur.page_end = max(cur.page_end, b.page)

    for s in sections:
        if s.kind not in SUBKINDS:
            s.text = "\n".join(b.text for b in s.blocks)
    # propagate page_end upward
    by_id = {s.section_id: s for s in sections}
    for s in sections:
        p = by_id.get(s.parent_section_id) if s.parent_section_id else None
        while p is not None:
            p.page_end = max(p.page_end, s.page_end)
            p = by_id.get(p.parent_section_id) if p.parent_section_id else None
    return sections


def _already_open(stack: list[SectionNode], heading: str) -> bool:
    return bool(stack) and _norm(stack[-1].heading) == _norm(heading)


def _anchors_from_outline(ex: PdfExtraction, blocks: list[Block]) -> dict[int, tuple[int, str]]:
    """Map block index -> (level, title) for each outline entry, matching on the entry's page (or next page)."""
    by_page: dict[int, list[int]] = {}
    for i, b in enumerate(blocks):
        by_page.setdefault(b.page, []).append(i)
    anchors: dict[int, tuple[int, str]] = {}
    used: set[int] = set()
    last_idx = -1
    for lvl, title, page in ex.outline:
        nt = _norm(title)
        if not nt or nt in {"contents", "index"}:
            continue
        best, best_score = None, 0.0
        for pg in (page, page + 1):
            for i in by_page.get(pg, []):
                if i in used or i <= last_idx - 400:
                    continue
                b = blocks[i]
                cand = _norm(b.text)
                if not cand:
                    continue
                score = fuzz.ratio(nt, cand[: max(len(nt) + 10, 20)])
                if cand.startswith(nt) and len(cand) < len(nt) + 40:
                    score = max(score, 96)
                if b.kind in ("heading", "line_heading"):
                    score += 4
                elif b.kind != "para":
                    score -= 10   # tip/caution/example bodies rarely are headings
                if score > best_score:
                    best, best_score = i, score
            if best is not None and best_score >= 85:
                break
        if best is not None and best_score >= 80:
            anchors[best] = (lvl, title)
            used.add(best)
            last_idx = best
    return anchors
