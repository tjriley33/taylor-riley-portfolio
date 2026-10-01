from taxrag.models import Citation, RetrievedChunk
from taxrag.retrieve.query import parse_query
from taxrag.retrieve.rerank import rerank, tax_score
from taxrag.answer.validate import validate_claims


def _chunk(**kw):
    base = dict(chunk_id="c", version_id="v", document_id="d", jurisdiction="US", tax_year=2025, form_number="1040", schedule=None, publication_number=None,
                document_type="instructions", draft_or_final="final", version_status="current", path_text="Doc > Income > Line 1a", kind="line",
                line_refs=["1a"], identifiers="form_1040 line_1a", text="Enter the total amount from Form(s) W-2, box 1.", provenance_class="PUBLIC_AUTHORITY")
    base.update(kw)
    return base


def test_wrong_state_or_year_is_demoted_even_with_higher_rrf():
    plan = parse_query("2025 Wisconsin Form 1 line 1")
    right = RetrievedChunk(chunk=_chunk(chunk_id="wi", jurisdiction="WI", form_number="1", path_text="Doc > Line 1", line_refs=["1"], identifiers="form_1 line_1"), scores={"rrf": 0.01})
    wrong_state = RetrievedChunk(chunk=_chunk(chunk_id="va", jurisdiction="VA", form_number="760", path_text="Doc > Line 1", line_refs=["1"], identifiers="form_760 line_1"), scores={"rrf": 0.03})
    wrong_year = RetrievedChunk(chunk=_chunk(chunk_id="wi24", jurisdiction="WI", form_number="1", tax_year=2024, path_text="Doc > Line 1", line_refs=["1"], identifiers="form_1 line_1"), scores={"rrf": 0.03})
    out = rerank(plan, [wrong_state, wrong_year, right], use_cross_encoder=False)
    assert out[0].chunk["chunk_id"] == "wi"
    assert any("WRONG JURISDICTION" in r for r in out[-1].reasons) or any("WRONG TAX YEAR" in r for r in out[-1].reasons)


def test_draft_demoted_unless_requested():
    plan = parse_query("Form 1040 line 1a")
    s_final, _, _ = tax_score(plan, _chunk(), "hybrid")
    s_draft, why, _ = tax_score(plan, _chunk(draft_or_final="draft"), "hybrid")
    assert s_final > s_draft and "DRAFT" in why
    plan2 = parse_query("draft Form 1040 line 1a")
    s_draft2, _, _ = tax_score(plan2, _chunk(draft_or_final="draft"), "hybrid")
    assert s_draft2 > s_draft


def _cit(cid, chunk_id, jur="US", year=2025, draft="final"):
    return Citation(citation_id=cid, chunk_id=chunk_id, version_id="v", document_id="d", agency="IRS", jurisdiction=jur, document_label="Instructions for Form 1040",
                    tax_year=year, revision=None, draft_or_final=draft, version_status="current", section_path="Doc > Line 1a", page=24, line_ref="1a",
                    source_url="u", local_url="l")


def test_validator_drops_manufactured_citations_and_labels_claims():
    plan = parse_query("Form 1040 line 1a wages 2025")
    chunks = {"c1": _chunk(chunk_id="c1")}
    cits = {"C1": _cit("C1", "c1")}
    raw = [
        {"text": "Wages come from Form W-2 box 1.", "citations": ["C1"], "quote": "total amount from Form(s) W-2, box 1", "label": "explicit"},
        {"text": "The standard deduction is $15,000.", "citations": ["C9"], "quote": "", "label": "explicit"},
        {"text": "Box 1 of W-2 is the total amount entered.", "citations": ["C1"], "quote": "this is not in the text", "label": "explicit"},
        {"text": "Something about penguins and glaciers.", "citations": ["C1"], "quote": "", "label": "derived"},
    ]
    claims, problems = validate_claims(raw, cits, chunks, plan)
    labels = [c.label for c in claims]
    assert labels[0] == "explicit"
    assert labels[1] == "not_established" and problems
    assert labels[2] == "derived" and any("downgraded" in n for n in claims[2].validation)
    assert labels[3] == "not_established"
