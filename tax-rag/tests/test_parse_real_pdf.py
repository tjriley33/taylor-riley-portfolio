"""Uses a real IRS PDF if present in the data dir (skipped otherwise)."""
from pathlib import Path

import pytest

from taxrag.parse import build_sections, extract_pdf


def _find_pdf():
    for p in Path("data/raw").glob("*.pdf"):
        if p.stat().st_size > 1_000_000:
            return p
    return None


@pytest.mark.skipif(_find_pdf() is None, reason="no ingested PDF available")
def test_real_pdf_structure():
    ex = extract_pdf(_find_pdf())
    assert ex.page_count > 5
    secs = build_sections(ex, "vtest", "Doc")
    assert len(secs) > 20
    assert all(s.page_start >= 1 for s in secs)
    assert max(s.level for s in secs) < 12
