"""hier_v1: one chunk per leaf section when small; paragraph-window split with overlap otherwise.
Every chunk carries the full hierarchy path and points at a section-level parent chunk."""
from __future__ import annotations

from ..config import settings
from ..models import ChunkRecord, SectionNode
from .common import approx_tokens, chunk_id, identifiers_for, line_refs_in

STRATEGY = "hier_v1"


def chunk_hierarchical(sections: list[SectionNode], version_id: str, doc: dict,
                       max_tokens: int | None = None, leaf_max: int | None = None) -> list[ChunkRecord]:
    max_tokens = max_tokens or settings.chunk_max_tokens
    leaf_max = leaf_max or settings.chunk_leaf_max_tokens
    out: list[ChunkRecord] = []
    ordinal = 0
    by_id = {s.section_id: s for s in sections}
    children: dict[str, list[SectionNode]] = {}
    for s in sections:
        if s.parent_section_id:
            children.setdefault(s.parent_section_id, []).append(s)

    for s in sections:
        text = s.text.strip()
        if not text:
            continue
        path_text = s.path_text
        # Parent/section-level chunk: heading + first ~2 paragraphs summary, used for expansion.
        parent_chunk: ChunkRecord | None = None
        head = f"{path_text}\n" if s.level > 0 else ""
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        if approx_tokens(text) <= leaf_max:
            ordinal += 1
            out.append(_mk(version_id, s, ordinal, head + text, path_text, doc, None))
            continue
        # Large section: parent chunk = heading + lead, children = windows
        lead = " ".join(paragraphs[:2])[:1200]
        ordinal += 1
        parent_chunk = _mk(version_id, s, ordinal, head + lead, path_text, doc, None)
        out.append(parent_chunk)
        window: list[str] = []
        wtok = 0
        prev_tail: str | None = None
        for para in paragraphs:
            ptok = approx_tokens(para)
            if wtok + ptok > max_tokens and window:
                ordinal += 1
                body = (prev_tail + "\n" if prev_tail else "") + "\n".join(window)
                out.append(_mk(version_id, s, ordinal, head + body, path_text, doc, parent_chunk.chunk_id))
                prev_tail = window[-1] if approx_tokens(window[-1]) < 120 else None  # limited overlap
                window, wtok = [], 0
            if ptok > max_tokens:  # giant paragraph: hard split by sentences
                sents = para.split(". ")
                cur = ""
                for snt in sents:
                    if approx_tokens(cur + snt) > max_tokens and cur:
                        ordinal += 1
                        out.append(_mk(version_id, s, ordinal, head + cur.strip(), path_text, doc, parent_chunk.chunk_id))
                        cur = ""
                    cur += snt + ". "
                if cur.strip():
                    # hard character cap for sentence-less blobs (tables rendered as text)
                    while approx_tokens(cur) > max_tokens:
                        ordinal += 1
                        out.append(_mk(version_id, s, ordinal, head + cur[: max_tokens * 4].strip(), path_text, doc, parent_chunk.chunk_id))
                        cur = cur[max_tokens * 4:]
                    if cur.strip():
                        window.append(cur.strip()); wtok += approx_tokens(cur)
                continue
            window.append(para)
            wtok += ptok
        if window:
            ordinal += 1
            body = (prev_tail + "\n" if prev_tail else "") + "\n".join(window)
            out.append(_mk(version_id, s, ordinal, head + body, path_text, doc, parent_chunk.chunk_id))
    return out


def _mk(version_id: str, s: SectionNode, ordinal: int, text: str, path_text: str, doc: dict, parent: str | None) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id(version_id, STRATEGY, ordinal, text), version_id=version_id, section_id=s.section_id,
        parent_chunk_id=parent, ordinal=ordinal, text=text, token_count=approx_tokens(text),
        page_start=s.page_start, page_end=s.page_end, path_text=path_text, kind=s.kind,
        line_refs=([s.line_ref] if s.line_ref else []) + [r for r in line_refs_in(text) if r != s.line_ref],
        identifiers=identifiers_for(text, path_text, doc), strategy=STRATEGY,
    )
