from taxrag.identify import identify_irs_filename, identify_irs_product, parse_revision, tax_types_for
from taxrag.models import DocumentType


def test_parse_revision():
    assert parse_revision("2025") == (2025, None)
    assert parse_revision("Jan 2024") == (None, "01-2024")
    assert parse_revision("0622") == (None, "06-2022")
    assert parse_revision("garbage") == (None, None)


def test_identify_product():
    f = identify_irs_product("Instruction 1040 (Schedule C)", "Instructions for Schedule C (Form 1040)")
    assert f["document_type"] == DocumentType.schedule_instructions and f["form_number"] == "1040" and f["schedule"] == "C"
    f = identify_irs_product("Publication 17", "Your Federal Income Tax")
    assert f["document_type"] == DocumentType.publication and f["publication_number"] == "17"
    f = identify_irs_product("Form 1040", "U.S. Individual Income Tax Return")
    assert f["document_type"] == DocumentType.form and f["form_number"] == "1040"


def test_identify_filename():
    assert identify_irs_filename("i1040gi.pdf")["document_type"] == DocumentType.instructions
    f = identify_irs_filename("f1040s1--dft.pdf")
    assert f["schedule"] == "1" and f["draft_or_final"] == "draft"
    f = identify_irs_filename("i1040gi--2024.pdf")
    assert f["tax_year"] == 2024
    assert identify_irs_filename("p17.pdf")["publication_number"] == "17"


def test_tax_types():
    assert tax_types_for("1040") == ["1040"]
    assert tax_types_for("1120-S") == ["1120S"]
    assert tax_types_for("990") == ["990"]
