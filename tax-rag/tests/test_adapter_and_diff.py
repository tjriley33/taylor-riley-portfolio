from taxrag.adapters.irs_pipeline import IRSPipelineAdapter, parse_form_desc, s3_key_for
from taxrag.models import DocumentType


def test_parse_form_desc():
    assert parse_form_desc("2025 Inst 1040 (Schedule C) (PDF)") == {"tax_year": 2025, "revision": None, "product": "Instruction 1040 (Schedule C)"}
    d = parse_form_desc("0622 Publ 5649 (PDF)")
    assert d["tax_year"] is None and d["revision"] == "06-2022" and d["product"] == "Publication 5649"


def test_s3_key_matches_legacy_scheme():
    assert s3_key_for("2025 Form 1040                            (PDF)", "https://www.irs.gov/pub/irs-dft/f1040--dft.pdf", True).startswith("Forms/Form 1040/")
    k = s3_key_for("2025 Inst 1040 (PDF)", "https://www.irs.gov/pub/irs-pdf/i1040gi.pdf", False)
    assert k == "Forms/Form 1040/2025 Final/i1040gi.pdf"


def test_dynamo_row_to_discovered():
    a = IRSPipelineAdapter(export_path="/nonexistent", live=False)
    rec = {"url": {"S": "https://www.irs.gov/pub/irs-pdf/i1040sc.pdf"}, "date_released": {"S": "2026-01-10 22:10:19"}, "status": {"S": "Final"},
           "form_desc": {"S": "2025 Inst 1040 (Schedule C) (PDF)"}, "is_1040": {"S": "X"}, "is_1065": {"S": ""}, "supported": {"BOOL": True}}
    from taxrag.adapters.irs_pipeline import _unmarshal
    d = a.to_discovered(_unmarshal(rec))
    assert d.identity.document_type == DocumentType.schedule_instructions
    assert d.identity.form_number == "1040" and d.identity.schedule == "C" and d.identity.tax_type == ["1040"]
    assert d.tax_year == 2025 and d.draft_or_final.value == "final" and d.release_date == "2026-01-10"
    assert d.upstream["s3_key"] == "Forms/Form 1040 (Schedule C)/2025 Final/i1040sc.pdf"


def test_section_diff(store):
    from taxrag.diff.sections import diff_versions
    from taxrag.models import SectionNode
    old = [SectionNode(section_id="o1", version_id="v1", parent_section_id=None, level=1, heading="Line 1a", kind="line", line_ref="1a",
                       path=["Doc", "Line 1a"], text="Enter wages from box 1. The limit is $100.", page_start=3, page_end=3),
           SectionNode(section_id="o2", version_id="v1", parent_section_id=None, level=1, heading="Gone", path=["Doc", "Gone"], text="Removed text.", page_start=4, page_end=4)]
    new = [SectionNode(section_id="n1", version_id="v2", parent_section_id=None, level=1, heading="Line 1a", kind="line", line_ref="1a",
                       path=["Doc", "Line 1a"], text="Enter wages from box 1. The limit is $200. See Pub. 525.", page_start=3, page_end=3),
           SectionNode(section_id="n2", version_id="v2", parent_section_id=None, level=1, heading="Brand New", path=["Doc", "Brand New"], text="Added text.", page_start=5, page_end=5)]
    store.replace_sections("v1", old)
    store.replace_sections("v2", new)
    ch = diff_versions(store, "v1", "v2")
    types = sorted(c["change_type"] for c in ch)
    assert "line_changed" in types and "section_added" in types and "section_removed" in types and "reference_changed" in types
    lc = next(c for c in ch if c["change_type"] == "line_changed")
    assert lc["old_page"] == 3 and lc["new_page"] == 3 and "$200" in lc["diff_text"]
