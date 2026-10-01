from taxrag.retrieve.query import parse_query


def test_wisconsin_schedule_year():
    p = parse_query("2025 Wisconsin Schedule I instructions")
    assert p.jurisdiction == "WI" and p.tax_year == 2025 and p.schedule == "I"
    assert p.hard_filters["jurisdiction"] == "WI" and p.hard_filters["tax_year"] == 2025
    assert p.hard_filters["draft_or_final"] == "final"
    assert p.document_type == "schedule_instructions"


def test_form_line_pub():
    p = parse_query("Form 1040 line 12 and Publication 17 for 2024")
    assert p.form == "1040" and p.line == "12" and p.publication == "17" and p.tax_year == 2024
    assert p.jurisdiction == "US"
    assert "form_1040" in p.identifiers and "line_12" in p.identifiers


def test_ny_form_implies_jurisdiction():
    p = parse_query("IT-201 instructions who must file")
    assert p.form == "IT-201" and p.jurisdiction == "NY"


def test_compare_intent():
    p = parse_query("What changed in Form 1040 Schedule 1 between 2025 and 2026?")
    assert p.compare_intent and p.tax_years == [2025, 2026] and p.schedule == "1"


def test_draft_words_allow_drafts():
    p = parse_query("Show me the latest draft Form 1040 instructions")
    assert p.include_drafts and "draft_or_final" not in p.hard_filters


def test_fts_query_is_valid_expression():
    p = parse_query("How do I report tip income on line 1a?")
    q = p.fts_query()
    assert 'identifiers:"line_1a"' in q and " OR " in q
