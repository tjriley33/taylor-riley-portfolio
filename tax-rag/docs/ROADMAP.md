# Roadmap (phases 5–6 and open items)

Done in this build: Phase 1 (federal MVP), Phase 2 (version intelligence: draft/final,
historical versions, section diffs, compare mode), Phase 3 framework + VA/NY/WI,
Phase 4 v1 (reference graph + graph-expanded retrieval).

## Phase 5 — TaxDev intelligence
* Impact view: for a `document_changes` row, list dependent documents via `relationships`
  (e.g. a changed Form 1040 line → every state instruction that references that line).
* LLM change summaries per diff (port `IRS-Forms/ai_summary.py` behind `taxrag/answer/llm.py`).
* Internal TaxDev collector (`provenance_class=INTERNAL_TAXDEV`), separate SQLite/Postgres schema, IAM boundary.
* Line-number remapping table across years (Line 1a ↔ Line 1a/1c renumbering) to make `line_changed` precise.

## Phase 6 — Full scale
* All states: implement `StateCollector` subclasses; most differ only in URL grammar. Prioritize by
  product coverage (states with 1040-equivalents + business returns).
* Extraction upgrade: Docling or Marker behind `taxrag.parse.extract_pdf` for unruled worksheets/tables.
* Postgres + pgvector (`docs/POSTGRES_MIGRATION.md`), OpenSearch for lexical at >5M chunks.
* Scheduled refresh (EventBridge → ECS), alerting on quarantines, drift detection on embedding model.
* Evaluation: analyst-reviewed gold set ≥300 items; nightly eval with regression gates on
  `chunk_hit@5`, `jurisdiction_ok`, `tax_year_ok`, `abstained_correctly`, `faithfulness`.
* UI: side-by-side version viewer with change highlighting; feedback loop into `query_log.feedback`.

## Known gaps
* Worksheet column alignment is lossy (text-only). Tables are captured as text, not cells.
* `fixed_512`/`page_v1` baselines re-chunk from stored section text, so their block granularity is coarser than the live parse.
* Draft watermark text ("DRAFT AS OF ...") remains in draft chunks (intentional: it is what the document says).
