from __future__ import annotations

from ..models import ChunkRecord, SectionNode
from .fixed import chunk_fixed, chunk_pages
from .hierarchical import chunk_hierarchical

STRATEGIES = {
    "hier_v1": chunk_hierarchical,
    "fixed_512": lambda s, v, d: chunk_fixed(s, v, d, 512, 64),
    "fixed_256": lambda s, v, d: chunk_fixed(s, v, d, 256, 32),
    "page_v1": chunk_pages,
}


def chunk_sections(strategy: str, sections: list[SectionNode], version_id: str, doc: dict) -> list[ChunkRecord]:
    if strategy not in STRATEGIES:
        raise KeyError(f"unknown chunk strategy {strategy}; known {sorted(STRATEGIES)}")
    return STRATEGIES[strategy](sections, version_id, doc)
