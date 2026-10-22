"""Baselines for the chunking experiment: fixed_512 (naive windows) and page_v1 (one chunk per page)."""
from __future__ import annotations

from ..models import ChunkRecord, SectionNode
from .common import approx_tokens, chunk_id, identifiers_for, line_refs_in


def chunk_fixed(sections: list[SectionNode], version_id: str, doc: dict, size: int = 512, overlap: int = 64) -> list[ChunkRecord]:
    strategy = f"fixed_{size}"
    # flatten in reading order with page tracking
    words: list[tuple[str, int, str]] = []
    for s in sections:
        for b in s.blocks:
            for w in b.text.split():
                words.append((w, b.page, s.path_text))
    out, ordinal, i = [], 0, 0
    step = max(1, int((size - overlap) * 0.75))  # ~0.75 words/token
    win = int(size * 0.75)
    while i < len(words):
        seg = words[i:i + win]
        if not seg:
            break
        text = " ".join(w for w, _, _ in seg)
        ordinal += 1
        out.append(ChunkRecord(chunk_id=chunk_id(version_id, strategy, ordinal, text), version_id=version_id, section_id=None,
                               parent_chunk_id=None, ordinal=ordinal, text=text, token_count=approx_tokens(text),
                               page_start=seg[0][1], page_end=seg[-1][1], path_text=seg[0][2], kind="window",
                               line_refs=line_refs_in(text), identifiers=identifiers_for(text, "", doc), strategy=strategy))
        i += step
    return out


def chunk_pages(sections: list[SectionNode], version_id: str, doc: dict) -> list[ChunkRecord]:
    strategy = "page_v1"
    pages: dict[int, list[str]] = {}
    paths: dict[int, str] = {}
    for s in sections:
        for b in s.blocks:
            pages.setdefault(b.page, []).append(b.text)
            paths.setdefault(b.page, s.path_text)
    out = []
    for n, (pg, texts) in enumerate(sorted(pages.items()), start=1):
        text = "\n".join(texts)
        out.append(ChunkRecord(chunk_id=chunk_id(version_id, strategy, n, text), version_id=version_id, section_id=None,
                               parent_chunk_id=None, ordinal=n, text=text, token_count=approx_tokens(text), page_start=pg, page_end=pg,
                               path_text=paths[pg], kind="page", line_refs=line_refs_in(text), identifiers=identifiers_for(text, "", doc),
                               strategy=strategy))
    return out
