# Build report — 2026-10-01 overnight build

What was built, what the numbers say, and what is left. Companion to `ARCHITECTURE.md`
(design) and `../PLUG_IN_LATER.md` (what you must supply).

## What exists now

| Area | Status |
|---|---|
| Architecture document (15 deliverables of brief §25) | `docs/ARCHITECTURE.md` |
| Collectors | `IRSCollector` (seeds + live current/prior/draft listing pages), `VirginiaCollector`, `NewYorkCollector`, `WisconsinCollector`, `ArkansasCollector` (scaffold; site blocks bots) |
| Existing-pipeline adapter | `IRSPipelineAdapter` reads the DynamoDB `Forms` export/live table and maps the S3 key scheme; validated on the real export: 2,204 rows → 688 supported English documents (313 forms, 220 instructions, 90 schedules, 40 schedule instructions, 25 pubs; 351 drafts / 337 finals) |
| Ingestion | idempotent, hash-versioned, stage-tracked, retry + quarantine, validation, automatic section diffs vs prior year / superseded hash / same-year final |
| Parsing | PyMuPDF layout extraction: column ordering, de-hyphenation, outline-anchored hierarchy, run-in heading split, TIP/CAUTION/Note/Example/Exception/Worksheet tagging, line-reference detection, OCR hook |
| Chunking | `hier_v1` (section-leaf chunks with parent expansion) + `fixed_512` / `fixed_256` / `page_v1` baselines for the experiment |
| Graph | 20k typed edges (form / schedule / publication / line / IRC / regulation / worksheet / state→federal conformity / instructions_for / schedule_of); dangling targets re-resolved after each run |
| Retrieval | filter-first BM25 (FTS5) ∥ vector (bge-small) → RRF → graph expansion → cross-encoder + deterministic tax score (hard demotion for wrong state / year / unrequested draft) → parent expansion → conflict detection |
| Answering | research / taxdev / source / compare / evidence; LLM optional (Anthropic or Bedrock); claim validator (manufactured-citation rejection, quote verification, explicit / derived / not_established labelling); abstention on insufficient evidence |
| API + UI | FastAPI (`/search /ask /compare /documents /versions /sections /chunks /sources /files /changes /graph /queries /feedback /admin/*`), single-page analyst console with PDF viewer at the cited page |
| Evaluation | 40-item gold set across 11 categories; per-metric scoring; chunking experiment runner |
| Tests / CI | 25 pytest tests; GitHub Actions workflow on `tax-rag/**` |
| Deployment | Dockerfile, `taxrag sync push|pull` (S3), CloudFormation (ECS Fargate API + nightly ingest task + S3 bucket) |
| Shipped index | `dist/taxrag-index-20261001.sqlite.gz` (40 MB); `make pull-index` unpacks it and re-fetches originals by hash |

## Corpus indexed

59 documents, 79 versions, 4 jurisdictions (US, VA, NY, WI), tax years 2023–2026 including
five TY2026 early-release drafts. Full list in the appendix.

## Evaluation (gold set, `hier_v1`, extractive mode, no LLM)

EVAL_TABLE_PLACEHOLDER

Reading the numbers: jurisdiction, tax-year and version accuracy are 1.0 because they are
enforced as filters and hard demotions, not learned. Faithfulness is 1.0 in extractive mode
by construction (verbatim quotes); the number that matters once an LLM key is added is the
validator's `explicit`/`derived` ratio, which the harness reports per run. The gold set was
written by the builder and has **not** been reviewed by a tax analyst, so treat these as
smoke-level numbers until it is.

## Chunking experiment

| metric | hier_v1 | fixed_512 | page_v1 |
|---|---|---|---|
| doc_hit@1 | 0.9 | 0.8 | 0.75 |
| doc_hit@5 | 0.9 | 0.875 | 0.9 |
| chunk_hit@1 | 0.875 | 0.675 | 0.65 |
| chunk_hit@5 | 0.875 | 0.7 | 0.75 |
| citation_ok | 0.875 | 0.675 | 0.65 |
| changes_found | 1.0 | 0.5 | 0.75 |
| completeness | 0.917 | 1.0 | 0.958 |
| abstained_correctly | 1.0 | 1.0 | 1.0 |
| line_specific (category) | 0.75 | 0.25 | 0.25 |
| tax_year_specific (category) | 1.0 | 0.333 | 0.333 |
| draft_final_comparison (category) | 1.0 | 0.333 | 0.333 |

Same corpus, same retrieval stack, same gold set (run on a copy of the index with all three
strategies embedded; `scripts/chunking_experiment.sh`). Hierarchical section chunks win on every
retrieval metric that matters for citations; the naive window baseline collapses on
line-specific and year-specific questions because windows straddle sections and lose the
line heading that the reranker keys on. `hier_v1` is the shipped default.

## Known gaps found during the build

1. **Diff noise.** Section alignment is by path then fuzzy heading within the same parent;
   when a document is re-outlined between years, many sections show as added/removed rather
   than moved. `section_modified` / `line_changed` rows are reliable; the added/removed
   counts over-state change. Next step: global fuzzy alignment on section text.
2. **Worksheets and tables** are captured as text blocks, not cells (`table_changed` barely fires).
3. **Outline coverage** is 85–95 % for IRS instructions, lower for forms (forms have no
   outline; headings are detected by font only) and for some state booklets.
4. **Draft watermark text** ("DRAFT AS OF …") stays in draft chunks by design.
5. **Latency** is 2–7 s per query on 4 CPU cores, dominated by the cross-encoder; set
   `TAXRAG_USE_CROSS_ENCODER=false` for ~0.3 s lexical+vector-only retrieval.
6. **Arkansas** blocked (HTTP 403 to scripted clients).

## Appendix — indexed versions

| Jur | Type | Form | Sched | Pub | Year | Status | Pages |
|---|---|---|---|---|---|---|---|
| NY | instructions | IT-201 |  |  | 2024 | final | 41 |
| NY | form | IT-201 |  |  | 2024 | final | 4 |
| NY | instructions | IT-201 |  |  | 2025 | final | 41 |
| NY | form | IT-201 |  |  | 2025 | final | 4 |
| NY | form | IT-201-ATT |  |  | 2025 | final | 2 |
| NY | instructions | IT-225 |  |  | 2025 | final | 21 |
| US | efile_spec |  |  | 1345 |  | final | 45 |
| US | publication |  |  | 17 | 2024 | final | 143 |
| US | publication |  |  | 17 | 2025 | final | 142 |
| US | efile_spec |  |  | 4164 | 2026 | final | 282 |
| US | publication |  |  | 501 | 2025 | final | 31 |
| US | publication |  |  | 525 | 2025 | final | 42 |
| US | publication |  |  | 590-A | 2025 | final | 62 |
| US | publication |  |  | 596 | 2025 | final | 42 |
| US | publication |  |  | 974 | 2025 | final | 68 |
| US | instructions | 1040 |  |  | 2023 | final | 114 |
| US | form | 1040 |  |  | 2024 | final | 2 |
| US | instructions | 1040 |  |  | 2024 | final | 113 |
| US | form | 1040 |  |  | 2025 | final | 2 |
| US | instructions | 1040 |  |  | 2025 | final | 126 |
| US | form | 1040 |  |  | 2026 | draft | 3 |
| US | instructions | 1040 |  |  | 2026 | draft | 127 |
| US | schedule | 1040 | 1 |  | 2024 | final | 2 |
| US | schedule | 1040 | 1 |  | 2025 | final | 2 |
| US | schedule | 1040 | 1 |  | 2026 | draft | 3 |
| US | schedule | 1040 | 2 |  | 2025 | final | 2 |
| US | schedule | 1040 | 3 |  | 2025 | final | 1 |
| US | schedule_instructions | 1040 | 8812 |  | 2025 | final | 9 |
| US | schedule | 1040 | 8812 |  | 2025 | final | 2 |
| US | schedule | 1040 | A |  | 2025 | final | 1 |
| US | schedule_instructions | 1040 | A |  | 2025 | final | 18 |
| US | schedule | 1040 | B |  | 2025 | final | 1 |
| US | schedule | 1040 | C |  | 2024 | final | 2 |
| US | schedule_instructions | 1040 | C |  | 2024 | final | 21 |
| US | schedule | 1040 | C |  | 2025 | final | 2 |
| US | schedule_instructions | 1040 | C |  | 2025 | final | 19 |
| US | schedule | 1040 | C |  | 2026 | draft | 3 |
| US | schedule | 1040 | D |  | 2025 | final | 2 |
| US | schedule_instructions | 1040 | D |  | 2025 | final | 16 |
| US | schedule | 1040 | E |  | 2025 | final | 2 |
| US | schedule_instructions | 1040 | E |  | 2025 | final | 11 |
| US | schedule_instructions | 1040 | E |  | 2026 | draft | 15 |
| US | schedule | 1040 | SE |  | 2025 | final | 2 |
| US | schedule_instructions | 1040 | SE |  | 2025 | final | 5 |
| US | form | 1041 |  |  | 2025 | final | 3 |
| US | instructions | 1041 |  |  | 2025 | final | 55 |
| US | instructions | 1065 |  |  | 2024 | final | 72 |
| US | instructions | 1065 |  |  | 2025 | final | 70 |
| US | form | 1065 |  |  | 2025 | final | 6 |
| US | schedule_instructions | 1065 | K-1 |  | 2025 | final | 36 |
| US | schedule | 1065 | K-1 |  | 2025 | final | 1 |
| US | instructions | 1120 |  |  | 2025 | final | 34 |
| US | form | 1120 |  |  | 2025 | final | 6 |
| US | instructions | 1120-S |  |  | 2025 | final | 56 |
| US | form | 1120-S |  |  | 2025 | final | 5 |
| US | schedule | 1120-S | K-1 |  | 2025 | final | 1 |
| US | schedule_instructions | 1120-S | K-1 |  | 2025 | final | 21 |
| US | instructions | 2441 |  |  | 2025 | final | 7 |
| US | form | 2441 |  |  | 2025 | final | 2 |
| US | form | 8949 |  |  | 2025 | final | 2 |
| US | instructions | 8949 |  |  | 2025 | final | 13 |
| US | instructions | 8962 |  |  | 2025 | final | 24 |
| US | form | 8962 |  |  | 2025 | final | 2 |
| US | instructions | 990 |  |  | 2025 | final | 102 |
| US | form | 990 |  |  | 2025 | final | 12 |
| VA | form | 760 |  |  | 2024 | final | 2 |
| VA | instructions | 760 |  |  | 2024 | final | 52 |
| VA | form | 760 |  |  | 2025 | final | 2 |
| VA | instructions | 760 |  |  | 2025 | final | 43 |
| VA | schedule | 760 | ADJ |  | 2025 | final | 2 |
| VA | schedule | 760 | CR |  | 2025 | final | 8 |
| VA | schedule_instructions | 760 | CR |  | 2025 | final | 12 |
| WI | instructions | 1 |  |  | 2024 | final | 46 |
| WI | form | 1 |  |  | 2024 | final | 5 |
| WI | instructions | 1 |  |  | 2025 | final | 46 |
| WI | form | 1 |  |  | 2025 | final | 5 |
| WI | schedule_instructions | 1 | I |  | 2024 | final | 9 |
| WI | schedule_instructions | 1 | I |  | 2025 | final | 9 |
| WI | schedule | 1 | I |  | 2025 | final | 2 |
