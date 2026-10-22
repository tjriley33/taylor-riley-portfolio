import numpy as np

from taxrag.models import Block, ChunkRecord, DocumentIdentity, DocumentType, SectionNode, VersionRecord
from taxrag.chunk import chunk_sections
from taxrag.chunk.common import identifiers_for


def _ident(**kw):
    base = dict(authority="irs", jurisdiction="US", agency="IRS", document_type=DocumentType.instructions, form_number="1040", tax_type=["1040"])
    base.update(kw)
    return DocumentIdentity(**base)


def test_document_id_is_deterministic_and_version_independent():
    a, b = _ident(title="x"), _ident(title="y")
    assert a.document_id == b.document_id
    assert _ident(form_number="1065").document_id != a.document_id


def test_versioning_keeps_both_hashes(store):
    did = store.upsert_document(_ident())
    v1 = VersionRecord(version_id="h1", document_id=did, tax_year=2025, revision=None, revision_date=None, release_date="2026-01-01",
                       draft_or_final="final", effective_date=None, source_url="s", download_url="https://x/i1040gi.pdf", retrieved_at="2026-01-02T00:00:00",
                       file_hash="h1", file_path="/tmp/h1.pdf", page_count=10)
    store.insert_version(v1)
    v2 = v1.model_copy(update={"version_id": "h2", "file_hash": "h2", "retrieved_at": "2026-02-02T00:00:00", "release_date": "2026-02-01"})
    store.insert_version(v2)
    prev = store.version_by_url_current("https://x/i1040gi.pdf")
    store.supersede("h1", "h2")
    store.recompute_current_status(did)
    vs = {v["version_id"]: v for v in store.versions_for_document(did)}
    assert vs["h1"]["status"] == "superseded" and vs["h2"]["status"] == "current"
    assert vs["h2"]["supersedes_version_id"] == "h1"
    assert len(vs) == 2  # nothing overwritten


def test_hierarchical_chunking_carries_path_and_line_refs():
    root = SectionNode(section_id="r", version_id="v", parent_section_id=None, level=0, heading="Instructions for Form 1040", path=["Instructions for Form 1040"])
    inc = SectionNode(section_id="a", version_id="v", parent_section_id="r", level=1, heading="Income", path=["Instructions for Form 1040", "Income"])
    line = SectionNode(section_id="b", version_id="v", parent_section_id="a", level=2, heading="Line 1a", kind="line", line_ref="1a",
                       path=["Instructions for Form 1040", "Income", "Line 1a"], page_start=24, page_end=24,
                       text="Enter the total amount from Form(s) W-2, box 1. See Pub. 525 for details on Schedule 1.")
    doc = {"form_number": "1040", "schedule": None, "publication_number": None, "jurisdiction": "US"}
    chunks = chunk_sections("hier_v1", [root, inc, line], "v", doc)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.path_text == "Instructions for Form 1040 > Income > Line 1a"
    assert "1a" in c.line_refs and c.page_start == 24
    assert "pub_525" in c.identifiers and "sched_1" in c.identifiers and "form_1040" in c.identifiers


def test_large_section_is_windowed_with_parent():
    big = SectionNode(section_id="b", version_id="v", parent_section_id=None, level=1, heading="Big", path=["Doc", "Big"],
                      text="\n".join(f"Paragraph {i} " + "word " * 120 for i in range(12)))
    doc = {"form_number": None, "schedule": None, "publication_number": None, "jurisdiction": "US"}
    chunks = chunk_sections("hier_v1", [big], "v", doc)
    assert len(chunks) > 2
    parent = chunks[0]
    assert all(c.parent_chunk_id == parent.chunk_id for c in chunks[1:])
    assert max(c.token_count for c in chunks) <= 700


def test_fts_and_vector_search_with_filters(store):
    did = store.upsert_document(_ident())
    v = VersionRecord(version_id="h1", document_id=did, tax_year=2025, revision=None, revision_date=None, release_date=None, draft_or_final="final",
                      effective_date=None, source_url="s", download_url="u", retrieved_at="t", file_hash="h1", file_path="p")
    store.insert_version(v)
    doc, ver = store.get_document(did), store.get_version("h1")
    chunks = [ChunkRecord(chunk_id=f"c{i}", version_id="h1", section_id=None, parent_chunk_id=None, ordinal=i, text=t, token_count=5, page_start=i,
                          page_end=i, path_text="Doc > Line 1a", kind="line", identifiers="form_1040 line_1a") for i, t in
              enumerate(["wages salaries and tips from Form W-2", "capital gains on Schedule D", "tip income not reported"], start=1)]
    store.replace_chunks("h1", "hier_v1", chunks, ver, doc)
    hits = store.fts_search('"tip" OR identifiers:"line_1a"', {"jurisdiction": "US", "tax_year": 2025, "strategy": "hier_v1"}, k=5)
    assert hits and hits[0][0] in {"c1", "c3"}
    assert store.fts_search('"tip"', {"jurisdiction": "VA", "strategy": "hier_v1"}) == []
    vecs = [("c1", np.array([1, 0, 0], dtype=np.float32)), ("c2", np.array([0, 1, 0], dtype=np.float32)), ("c3", np.array([0.9, 0.1, 0], dtype=np.float32))]
    store.replace_embeddings(vecs, "m", "hier_v1")
    res = store.vector_search(np.array([1, 0, 0], dtype=np.float32), {"jurisdiction": "US"}, "m", "hier_v1", k=2)
    assert [r[0] for r in res] == ["c1", "c3"]
    assert store.vector_search(np.array([1, 0, 0], dtype=np.float32), {"tax_year": 2024}, "m", "hier_v1") == []


def test_identifiers_for_state_forms():
    ids = identifiers_for("See Form IT-201, line 19 and federal Form 1040", "", {"jurisdiction": "NY", "form_number": "IT-201"})
    assert "form_it-201" in ids and "form_1040" in ids and "line_19" in ids and "jur_ny" in ids
