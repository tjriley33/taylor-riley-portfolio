# Federal + State Tax RAG — Architecture

Status: v1 (written before implementation, updated after the Phase 1/2 build).
Guiding principle: **"Can a tax analyst prove where this answer came from?"**

This document is the deliverable requested in section 25 of the brief. It is
organized in the same 15 parts. The implementation in `taxrag/` follows it.

---

## 1. Current-state assessment

### What exists

| Asset | Where | What it does | Reusable? |
|---|---|---|---|
| IRS release tracker (`main.py`) | `tjriley33/IRS-Forms`, deployed as Lambda `New_IRS_Forms` | Scrapes `irs.gov/downloads/irs-dft` and `irs-pdf` listing tables, detects new rows vs. DynamoDB, downloads PDFs, strips draft watermark page, uploads to S3, optionally runs an Apryse text-diff and a Bedrock summary, emails owners. | Yes, as an **upstream source of truth** for federal discovery and release detection. |
| DynamoDB table `Forms` (us-east-1) | AWS | One row per release: `url`, `date_released`, `status` (Draft/Final), `form_desc` (`"2025 Form 1040 (PDF)"` / `"0622 Publ 5649 (PR) (sp) (PDF)"`), `is_1040 … is_990` ("X"/""), `Is_Form`/`Inst`/`Pub` flags, `supported`, `owner`, `file_size`. 2,204 rows in the Aug-2026 export (1,572 Final, 592 Draft). | Yes. Mapped 1:1 onto our `DocumentVersion` by the adapter in `taxrag/adapters/irs_pipeline.py`. |
| S3 bucket `forms123456` | AWS | Key scheme `Forms/{form name}/{year or "Revision MM.YY"} {Draft|Final}/{filename}.pdf`, plus `compare_*.pdf` diff renders. | Yes, as a raw-object store for federal PDFs. |
| `forms_data.json` (461 forms) | IRS-Forms | Supported-forms catalog with `lookup` URL fragments, `tax_types` (1040/1065/1120/1120S/1041/990), `inst_included`. | Yes, used as the **tax_type classifier** seed. |
| `pyPdfCompare.py` | IRS-Forms | Apryse `AppendTextDiff` visual diff. Demo license key. | Partially. Visual diff only; no section semantics. We keep it as an optional "open visual diff" link and do structural diffing ourselves. |
| `ai_summary.py` | IRS-Forms | Bedrock Claude summary of a compare PDF. | Pattern reused for the LLM layer (Anthropic API or Bedrock, selectable). |
| `tax-assistant` | public repo | Front-end was removed 2026-09-10; backend (API Gateway, Cognito, Lambdas) still running for IRS-Forms. | Not needed. Cognito could later front the RAG API. |

### Gaps the existing pipeline does not cover

* No text extraction, no structure, no search of any kind.
* Change detection is by `date_released`/`file_size`/`form_desc` on the listing
  row, not by content hash. A silently replaced PDF at the same URL with the
  same listing row is **not** detected.
* No prior-year coverage (only the two "recent downloads" listing pages, 3 pages each).
* No states.
* Secrets: `setupdb.py` has a committed SQL Server `sa` password (flagged in
  that repo's README). Not used by this project; should still be rotated.
* Draft watermark stripping removes the cover page, which changes page
  numbering of drafts relative to the official PDF. The RAG system cites the
  **original** PDF page, so we never ingest the stripped copy as the canonical file.

### Environment constraints discovered during this build

* Network: irs.gov, tax.virginia.gov, tax.ny.gov, revenue.wi.gov reachable.
  **dfa.arkansas.gov returns 403 to non-browser clients** (bot protection).
* No Docker daemon in the build container; Postgres/OpenSearch could not be
  run here, which drove the "SQLite-first, Postgres-ready" storage decision.
* No OCR engine (tesseract) installed. OCR is a pluggable fallback that flags
  pages rather than failing.
* No LLM API key in the build environment. Everything except synthesized
  answers works without one; `ask` degrades to an extractive answer with
  citations and says so.

---

## 2. Proposed architecture

```
 ┌───────────────────────────────┐   ┌──────────────────────────────┐
 │ Existing IRS-Forms pipeline   │   │ TaxAuthorityCollector impls  │
 │ (Lambda → S3 + DynamoDB)      │   │ IRS · VA · NY · WI · (next)  │
 └──────────────┬────────────────┘   └──────────────┬───────────────┘
                │ IRSPipelineAdapter                │ discover()/fetch()
                ▼                                   ▼
        ┌──────────────────────────────────────────────────┐
        │  Raw object store  (data/raw/<sha256>.pdf)        │  immutable, content-addressed
        └──────────────────────┬───────────────────────────┘
                               ▼
        ┌──────────────────────────────────────────────────┐
        │  Document processor                                │
        │  identify → extract (PyMuPDF, layout+outline)      │
        │  → normalize → enrich → chunk → references         │
        └──────────────────────┬───────────────────────────┘
                               ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ Structured store (SQLite now / Postgres later), one file:     │
   │ documents · document_versions · sections · chunks ·          │
   │ chunk_fts (FTS5/BM25) · embeddings (float32 blobs) ·          │
   │ relationships · document_changes · ingestion_runs ·          │
   │ query_log · eval_*                                           │
   └──────────────────────┬───────────────────────────────────────┘
                          ▼
   Query understanding → filter plan → [vector ∥ BM25] → RRF fuse →
   graph expansion → cross-encoder + tax-aware rerank → parent expansion →
   conflict detection → context builder → LLM (optional) → citation validator
   → structured answer (claims labelled explicit / derived / not-established)
```

Everything is a plain Python package with a CLI (`taxrag`) and a FastAPI app.
Every stage writes to the same store, so any stage can be re-run alone.

---

## 3. Component choices and alternatives

| Concern | Chosen | Why | Rejected alternatives |
|---|---|---|---|
| Language/runtime | Python 3.11 | Matches the existing pipeline, best PDF/ML library coverage. | TypeScript (weaker PDF tooling). |
| PDF extraction | **PyMuPDF** (`pymupdf`) with layout heuristics + document outline | Fast (126-page 1040 instructions in ~2s), gives span-level font/size/bold, embedded links, and the PDF bookmark outline which IRS and most state PDFs carry (338 entries for i1040gi). Supports OCR hook if tesseract present. | `pdfplumber` (slow, no outline, used by the old pipeline for tables only); `pypdf` (text only, loses layout); Docling/Marker/Unstructured (much better tables but 1–3 GB of model weights and 10–50× slower; **recommended as Phase 6 upgrade** behind the same `Extractor` interface); AWS Textract (accurate, vendor-locked, ~$1.50/1k pages). |
| Embeddings | **fastembed** running `BAAI/bge-small-en-v1.5` (384-d, ONNX, CPU) | Runs locally with no key, ~30 MB, good enough for passage retrieval when paired with BM25 and a reranker. Swappable via `TAXRAG_EMBED_MODEL`. | OpenAI/Voyage/Bedrock Titan (better quality, API cost, key needed, vendor lock); `bge-base`/`bge-large` (2–4× slower on CPU; one env var to switch). |
| Reranker | **fastembed cross-encoder** `Xenova/ms-marco-MiniLM-L-6-v2` + deterministic tax-aware score | Cross-encoder catches semantic relevance; the deterministic layer enforces jurisdiction/year/form/draft rules so a wrong-state passage can never win on fluency. | Cohere Rerank (strong, API); `bge-reranker-v2-m3` (better, ~2 GB); LLM reranking (slow, non-deterministic, costly). |
| Lexical index | **SQLite FTS5** (BM25, porter stemming, prefix) | Zero infra, in the same file as everything else, supports exact identifier tokens via a separate `identifiers` column. | OpenSearch/Elasticsearch (Phase 6 at scale, strongly recommended when >5M chunks or multi-node); Tantivy (good, extra binary); Postgres `tsvector` (fine, no BM25 by default). |
| Vector index | **numpy brute force over float32 blobs in SQLite**, filter-first | At ≤500k chunks a filtered brute-force dot product is <50 ms and exact; metadata filtering happens *before* the vector scan, which is the whole point (section 7 of the brief). | pgvector (Phase 3+ target; same interface), Qdrant/Weaviate/Milvus (extra service), FAISS (approximate, filter-after is the wrong order for us), sqlite-vec (not yet stable enough on 3.45). |
| Structured store | **SQLite** via a `Store` interface | Single file, ACID, FTS5 built in, trivially shippable with the repo so the system is queryable with zero setup. Schema uses only portable SQL. | **Postgres + pgvector** is the intended production target (same schema, `Store` subclass; see `docs/POSTGRES_MIGRATION.md`). DynamoDB (poor for compound filtered queries over sections/chunks). |
| Knowledge graph | relationship table in SQL (`relationships`) with typed edges | Edges are few millions at most; 1–2 hop expansion is a SQL join. | Neo4j (operational cost, not needed for ≤2 hops), RDF stores. |
| Diffing | Section-aligned diff (`difflib` + hierarchy-path matching + rapidfuzz) | Produces `section_added/removed/modified`, `line_changed`, `table_changed`, `reference_changed`, each pointing to both versions' pages. | Apryse visual diff (kept as optional link), binary PDF diff (useless for RAG). |
| LLM | Anthropic Claude via `anthropic` SDK; Bedrock supported | Already used by the owner (auto-blog uses Anthropic; IRS-Forms uses Bedrock Claude). Strict JSON claim schema with citation ids. | OpenAI (fine; `LLMClient` interface), local Llama via Ollama (quality too low for tax). |
| API | FastAPI + uvicorn | Typed Pydantic schemas, OpenAPI docs at `/docs`. | Flask, Lambda-only (FastAPI runs on Lambda via Mangum later). |
| UI | Single static HTML/JS page served by FastAPI, PDF.js-compatible `#page=N` links | Analyst tool, not a product; zero build step. | React/Next (overkill for v1). |
| Scheduling | `taxrag refresh` CLI; cron / GitHub Actions / EventBridge | Idempotent, so any scheduler works. | Airflow/Step Functions (Phase 6). |

---

## 4. Data model

See `taxrag/store/schema.sql` for the executable version. Core entities:

### documents
Stable identity of a *tax product* independent of version.
`document_id` (PK, deterministic: `sha1(authority|jurisdiction|doc_type|form_number|schedule|pub_number|tax_type)`),
`authority` (`irs`, `va_tax`, `ny_dtf`, `wi_dor`, …), `jurisdiction` (`US`, `VA`, …),
`agency`, `document_type` (`form`, `instructions`, `publication`, `schedule`,
`schedule_instructions`, `notice`, `rev_proc`, `rev_rul`, `efile_spec`,
`schema`, `business_rules`, `faq`, `guide`), `form_number`, `form_name`,
`schedule`, `publication_number`, `tax_type` (JSON list of 1040/1065/1120/1120S/1041/990/…),
`title`, `provenance_class` (`PUBLIC_AUTHORITY` | `INTERNAL_TAXDEV`).

### document_versions
One row per distinct file content. `version_id` (PK = `sha256` of bytes),
`document_id`, `tax_year`, `revision`, `revision_date`, `release_date`,
`draft_or_final` (`draft`/`final`/`superseded`), `effective_date`, `source_url`,
`download_url`, `retrieved_at`, `file_hash`, `file_path`, `page_count`,
`supersedes_version_id`, `status` (`current`/`superseded`/`withdrawn`),
`ingest_state` (`downloaded`/`parsed`/`chunked`/`embedded`/`indexed`/`failed`/`quarantined`),
`title_in_pdf`, `pdf_metadata` JSON, `upstream` JSON (e.g. the DynamoDB row).

Same URL + new hash ⇒ new `version_id`, old row flipped to `superseded`,
`supersedes_version_id` set on the new one. **Nothing is ever overwritten.**

### sections
Hierarchy nodes from the outline/headings. `section_id`, `version_id`,
`parent_section_id`, `level`, `heading`, `path` (JSON list of headings from root),
`path_text` (`"Income > Line 1 > Wages, Salaries, Tips"`), `kind`
(`section`, `line`, `worksheet`, `table`, `example`, `caution`, `tip`, `note`,
`definition`, `exception`), `line_ref` (`"1a"`), `page_start`, `page_end`,
`char_start`, `char_end`, `text`, `ordinal`.

### chunks
Retrieval units. `chunk_id`, `version_id`, `section_id`, `parent_chunk_id`,
`ordinal`, `text`, `text_hash`, `token_count`, `page_start`, `page_end`,
`path_text`, `kind`, `line_refs` JSON, `identifiers` (space-separated normalized
identifiers such as `form_1040 sched_c line_12 pub_17`), `strategy`
(`hier_v1`, `fixed_512`, … so chunking experiments coexist), denormalized
filter columns: `jurisdiction`, `tax_year`, `form_number`, `document_type`,
`draft_or_final`, `authority`, `provenance_class`.

### chunk_fts (FTS5 virtual table)
`text`, `path_text`, `identifiers`, content-synced to `chunks`. BM25 with
column weights (identifiers 4.0, path 2.0, text 1.0).

### embeddings
`chunk_id`, `model`, `dim`, `vector` BLOB (float32), `strategy`. Loaded into a
per-filter numpy matrix at query time.

### relationships
`rel_id`, `src_type` (`document`/`version`/`section`/`chunk`), `src_id`,
`rel_type` (`references_form`, `references_schedule`, `references_publication`,
`references_line`, `references_irc`, `references_reg`, `references_worksheet`,
`conforms_to_federal`, `instructions_for`, `schedule_of`, `efile_rule_for`,
`supersedes`), `dst_type`, `dst_id` (resolved `document_id` when possible),
`dst_label` (raw text, e.g. `"Form 8949"`), `dst_jurisdiction`, `confidence`,
`evidence_page`.

### document_changes
`change_id`, `old_version_id`, `new_version_id`, `change_type`
(`section_added/removed/modified`, `line_changed`, `table_changed`,
`reference_changed`), `old_section_id`, `new_section_id`, `path_text`,
`old_page`, `new_page`, `similarity`, `diff_text` (unified), `summary`.

### citations
Materialized per answer: `citation_id`, `query_id`, `chunk_id`, `version_id`,
`section_id`, `page`, `line_ref`, `quote`, `label` (`explicit`/`derived`),
`validated` (bool), `validation_notes`.

### ingestion_runs / ingestion_items
`run_id`, `collector`, `started_at`, `finished_at`, `status`, `stats` JSON;
per item: `version_id`, `stage`, `status`, `error`, `attempts`, `quarantined`.

### query_log
`query_id`, `ts`, `mode`, `question`, `parsed` JSON, `filters` JSON,
`candidates` JSON (chunk ids with vector/bm25/rrf/rerank scores and the
reason each was retrieved), `context_chunk_ids`, `citations`, `answer` JSON,
`latency_ms` JSON per stage, `model`, `embed_model`, `tokens` JSON,
`confidence`, `failure` (nullable), `feedback` (nullable).

### evaluation_questions / evaluation_results
Gold set rows: `qid`, `question`, `mode`, `expected_document_ids`,
`expected_version_filters`, `expected_section_paths`, `expected_pages`,
`expected_answer_type` (`answer`/`insufficient_evidence`), `notes`, `reviewer`.
Results: `run_id`, `qid`, `strategy`, per-metric booleans/scores, `latency_ms`.

### Indexing choices

The dominant query is: *filter hard on (jurisdiction, tax_year, form_number,
document_type, draft_or_final, provenance_class)* then rank. So:

* `chunks(jurisdiction, tax_year, form_number, document_type, draft_or_final)`
  compound index — leftmost columns are the ones almost always present.
* `chunks(version_id, ordinal)` for parent/neighbor expansion.
* `document_versions(document_id, tax_year, draft_or_final, status)` for
  "latest final for year" resolution.
* `sections(version_id, path_text)` for diff alignment and direct section lookup.
* `relationships(src_id, rel_type)` and `(dst_id, rel_type)` for both directions.
* `document_changes(old_version_id, new_version_id)` and `(path_text)`.
* FTS5 handles lexical; the vector scan reads only the rows the SQL filter
  returns, so no vector index is needed at this scale. On Postgres the same
  columns become a composite B-tree plus a partial IVFFlat/HNSW per
  `provenance_class`.

---

## 5. Ingestion architecture

```
discover → download → hash/dedupe → identify → extract → normalize →
enrich → chunk → embed → lexical index → store → validate
```

* **Collectors** implement `TaxAuthorityCollector` (`discover_documents()`,
  `fetch_document()`, `extract_metadata()`, `normalize_document()`) and yield
  `DiscoveredDocument` records (URL + whatever the listing page knows).
  Implemented: `IRSCollector` (current listing, prior-year listing, draft
  listing, plus a curated seed list), `VirginiaCollector`, `NewYorkCollector`,
  `WisconsinCollector`. `ArkansasCollector` is scaffolded but the site blocks
  non-browser clients (see risks).
* **IRSPipelineAdapter** reads the existing DynamoDB `Forms` table (or its JSON
  export) and S3 bucket and emits the same `DiscoveredDocument` records, so the
  Lambda keeps being the federal release detector and we never re-crawl what it
  already found. The adapter maps `form_desc` → tax_year/revision + document
  type, `is_*` → tax_type, `status` → draft/final, S3 key → local raw path.
* **Idempotency**: raw bytes are content-addressed (`data/raw/<sha256>.pdf`).
  If the hash already exists as a `version_id`, download is skipped and the
  version is only advanced through stages it has not completed
  (`ingest_state`). A changed URL target produces a new version and links
  `supersedes_version_id`.
* **Status/failure tracking**: every stage writes `ingestion_items`; failures
  record the exception, increment `attempts`; after 3 failures the item is
  `quarantined` and excluded from retrieval until manually released
  (`taxrag quarantine --release`).
* **Validation** stage checks: page count > 0, ≥60% of pages have extractable
  text (else flagged `needs_ocr`), at least one section, chunk count sane,
  embeddings count == chunk count, FTS row count == chunk count.

---

## 6. Retrieval architecture

1. **Query understanding** (`taxrag/retrieve/query.py`): regex + gazetteer
   extraction of jurisdiction (state names/abbrevs, "federal"), tax year
   (4-digit years, "this year/last year" relative to configured current year),
   tax type (1040/1065/…), form (`Form 1040`, `IT-201`, `Form 760`, `Form 1`),
   schedule (`Schedule C`, `Sch. 1`), line (`line 12a`), publication
   (`Pub 17`), document type words ("instructions", "form", "publication",
   "draft"), topic (residual text), comparison intent (two years / "changed").
2. **Filter plan**: hard filters for jurisdiction and tax_year when stated;
   soft boosts otherwise. Default `draft_or_final = final` unless the user
   says draft, the mode is taxdev, or no final exists for that year
   (fallback is explicit and labelled).
3. **Hybrid candidates**: BM25 over FTS5 (identifier column boosted) ∥
   filtered vector scan. Top-50 each, fused with Reciprocal Rank Fusion.
4. **Relationship expansion**: for top-k candidates, follow `relationships`
   one hop (e.g. a section that says "see Pub. 525" pulls Pub 525's matching
   section) with a score penalty, tagged `via=graph`.
5. **Reranking**: cross-encoder score + deterministic tax score
   (exact form match, jurisdiction match, year match, line match, final>draft,
   identifier overlap, authority weight). Wrong jurisdiction / wrong year when
   the user specified one is a hard demotion, not a soft penalty.
6. **Parent expansion**: the chunk's `section` text (bounded) is attached so
   the LLM sees the authoritative context, while the citation stays on the
   precise chunk/page.
7. **Conflict detection**: among final context chunks, flag pairs with the
   same topic but different `jurisdiction`, `tax_year`, `draft_or_final`, or
   `document_type ∈ {publication, instructions}`; report, don't resolve.

---

## 7. Chunking strategy

Primary strategy `hier_v1`:

* Build the hierarchy from the PDF outline when present (IRS and most states),
  else from font-size/bold heading detection (14pt bold = section, 12pt bold =
  subsection, `Line \d+` bold = line heading). Run-in headings ("**Line 1** Enter
  gross receipts…" in one PDF block) are split so they can anchor; TIP/CAUTION
  icons are attached to the italic paragraph beside them, never to a heading.
* Split pages into columns by x-position, read column-major, dehyphenate
  line-end hyphens, join lines into paragraphs, detect `TIP`/`CAUTION`/`Note.`
  /`Example.`/`Exception.` markers and emit them as `kind`-tagged blocks,
  detect bullets, detect worksheets/tables (ruled regions via
  `page.find_tables()` plus "Worksheet" headings).
* Chunk = one leaf section (line instruction, worksheet, table, example) if
  ≤ 700 tokens; otherwise split at paragraph boundaries into ≤ 450-token
  windows with 1-paragraph overlap. Each chunk carries the full `path_text`,
  `line_refs`, `kind`, and `identifiers`.
* Every chunk points to its `section_id` and to a `parent_chunk_id` (the
  section-level chunk) for expansion.

Alternates implemented for the evaluation harness: `fixed_512` (naive,
512-token windows with 64 overlap) and `page_v1` (one chunk per page). The
harness (`taxrag eval --strategy`) reports retrieval metrics per strategy.

---

## 8. Versioning strategy

* Identity: `document_id` is the product; `version_id` is the bytes.
* Tax-year vs. revision: IRS tax-year products carry `tax_year`; continuous-use
  products carry `revision` (`"12-2023"`) and `tax_year = NULL`.
* `draft_or_final`: from the source (irs-dft path / "Draft" status / state
  listing label) and from the PDF text ("DRAFT AS OF" / "Do not file").
* `status`: `current` for the newest version of (document, tax_year,
  draft_or_final); earlier ones become `superseded` with `supersedes_version_id`.
* "What did the 2025 instructions say?" ⇒ filter `tax_year=2025` and
  `draft_or_final=final` and `status=current` (the final-as-last-published).
  "What do the current instructions say?" ⇒ newest `tax_year` with a final.
  Both are explicit filter plans in `taxrag/retrieve/query.py`; the answer
  always states which version it used.
* Same-URL replacement: hash differs ⇒ new version; both kept, old one
  superseded; a `document_changes` diff is computed automatically.

---

## 9. Citation design

Every claim in a synthesized answer must cite ≥1 `chunk_id` present in the
context. The validator:

1. rejects citations to ids not in the context (**manufactured**);
2. checks that the quoted span (if any) is a fuzzy substring (≥ 0.85 ratio) of
   the chunk text;
3. checks jurisdiction / tax_year / draft status of the cited version against
   the query filter plan;
4. labels each claim `explicit` (quote found), `derived` (no quote but the
   cited chunk shares ≥ 3 content terms with the claim), or
   `not_established` (dropped from the answer and listed separately).

Rendered form: `IRS, 2025 Instructions for Form 1040 (final), Line 1a, p. 24
— https://www.irs.gov/pub/irs-pdf/i1040gi.pdf#page=24`. The UI opens the
locally stored original at the page; the "official" link goes to the source URL.

---

## 10. Evaluation methodology

* Gold set `eval/gold.yaml`, human-reviewed, ≥10 categories listed in the
  brief, each item has expected `document_id`s, optional expected
  `path_text` fragments / pages, expected jurisdiction/year/version, and
  `expected_answer_type` (`answer` or `insufficient_evidence`).
* Metrics computed independently: document hit@k, chunk/section hit@k,
  citation accuracy (cited page within ±1 of expected, path overlap),
  jurisdiction accuracy, tax-year accuracy, version accuracy (draft/final,
  current/superseded), faithfulness (validator pass rate on LLM claims),
  completeness (expected key phrases present), and correct abstention rate.
* Chunking experiment: same gold set, `--strategy hier_v1|fixed_512|page_v1`.
* Nothing in the harness scores on whether the prose "sounds right".

---

## 11. Security / provenance model

* `provenance_class` on every document, version, chunk and citation:
  `PUBLIC_AUTHORITY` or `INTERNAL_TAXDEV`. It is a **hard filter** in every
  retrieval path; the context builder refuses to mix classes unless the
  request opts in (`include_internal=true`), and internal chunks are rendered
  under a separate "Internal knowledge (not authority)" heading with a
  different citation format (`INTERNAL:` prefix). The answer schema forbids
  labelling an internal citation as `authority`.
* Raw files are immutable and content-addressed; the store records the exact
  bytes hash that every citation points to.
* No secrets in the repo; configuration via env vars (`TAXRAG_*`,
  `ANTHROPIC_API_KEY`, AWS creds via the standard chain).
* Internal store can live in a separate SQLite file / Postgres schema with
  separate IAM; the `Store` interface takes a list of stores.

---

## 12. Estimated infrastructure requirements

| Scale | Corpus | Chunks | Storage | Compute |
|---|---|---|---|---|
| Phase 1–2 (this build) | ~40 federal + state PDFs, 2–3 years | ~15–25k | < 500 MB incl. PDFs | laptop / 1 vCPU container; ingest ≈ 1–2 s/page, embed ≈ 150 chunks/s CPU |
| Phase 3 (6–8 states, 3 years) | ~600 PDFs | ~250k | ~5 GB | 2 vCPU, 8 GB; SQLite still fine |
| Phase 6 (50 states, 5 years, pubs, e-file specs) | ~15–25k PDFs | 5–10M | 100–200 GB raw, 30–60 GB index | Postgres + pgvector (r6g.large) or OpenSearch 2-node; batch embedding on a c6i.2xlarge ≈ 6 h; or Bedrock Titan/Cohere embeddings ≈ $100–300 one-time |

API: single container (ECS Fargate 1 vCPU / 2 GB) serves < 1 s p50 without
LLM; LLM adds 3–10 s. Reranker on CPU adds ~150–400 ms for 60 candidates.

---

## 13. Phased implementation plan

| Phase | Scope | Status in this repo |
|---|---|---|
| 1 Federal MVP | IRS forms/instructions/pubs, hybrid search, filters, citations, UI, eval | **Done** |
| 2 Version intelligence | draft/final, historical versions, year compare, section diff | **Done** (diff is structural; LLM change summary optional) |
| 3 State framework | collector interface, VA + NY + WI onboarded; AR scaffolded | **Done** for VA/NY/WI; AR blocked (403) |
| 4 Relationship intelligence | reference extraction, graph expansion, state→federal conformity edges | **Done (v1)**: form/schedule/pub/line/IRC/reg refs; graph-expanded retrieval |
| 5 TaxDev intelligence | change workflows, impact view, INTERNAL_TAXDEV ingestion | Partial: taxdev answer mode + change queries; internal collector interface stubbed |
| 6 Full scale | all states, Postgres/OpenSearch, Docling extraction, monitoring, scheduled refresh | Planned; see `docs/ROADMAP.md` |

---

## 14. Repository / file structure

```
tax-rag/
  pyproject.toml            package + CLI entry point `taxrag`
  Makefile                  bootstrap / ingest / serve / eval / test
  README.md                 runbook
  PLUG_IN_LATER.md          things the owner must supply (keys, AWS, states)
  docs/                     this file, POSTGRES_MIGRATION.md, ROADMAP.md
  taxrag/
    config.py               settings (env TAXRAG_*)
    models.py               pydantic domain models
    identify.py             filename/title → form/schedule/pub/year/draft
    store/                  schema.sql, sqlite.py (Store), filters.py
    collectors/             base.py, irs.py, virginia.py, new_york.py, wisconsin.py, arkansas.py, seeds/*.yaml
    adapters/irs_pipeline.py   DynamoDB/S3 → DiscoveredDocument
    parse/                  pdf.py (PyMuPDF layout), structure.py (hierarchy), blocks.py
    chunk/                  hierarchical.py, fixed.py, page.py, registry.py
    graph/references.py     cross-reference extraction + resolution
    embed/                  fastembed wrapper, batch embedding
    ingest/pipeline.py      stage runner, idempotency, quarantine
    diff/sections.py        version diffing
    retrieve/               query.py, hybrid.py, rerank.py, expand.py, conflicts.py
    answer/                 modes.py, llm.py, validate.py, prompts.py
    api/app.py              FastAPI
    ui/index.html           analyst UI
    eval/                   gold.yaml, harness.py
    observability.py        query log + debug view
  tests/                    pytest
  data/                     raw/, taxrag.sqlite (gitignored except seed)
```

---

## 15. Risks and unresolved questions

1. **Arkansas (and other bot-protected DORs)** return 403 to scripted
   clients. Options: Playwright-driven fetch (installed Chromium is available),
   or manual drops into `data/inbox/<state>/`. Decision needed on acceptable
   crawling posture per state.
2. **Table/worksheet fidelity.** PyMuPDF's `find_tables` works on ruled
   tables; IRS worksheets are often unruled. Worksheets are captured as text
   blocks with `kind=worksheet` but column alignment can be lossy. Docling in
   Phase 6.
3. **OCR** not available in this environment; scanned state PDFs (older
   years) will be flagged `needs_ocr` and excluded from retrieval until OCR
   is enabled (`pip install pytesseract` + system tesseract).
4. **Draft page numbering.** The existing pipeline strips the draft cover
   page; we cite original pages. The adapter re-downloads the original from
   `source_url` when the S3 copy hash differs from the original.
5. **State "current forms" URLs** (NY `current_forms/`, VA `vatax-pdf/`)
   are overwritten each year; the hash-versioning handles it but the first
   crawl can't recover history except via the states' prior-year pages,
   which are implemented for NY and VA, and WI (year-stamped URLs).
6. **LLM availability.** Without `ANTHROPIC_API_KEY` (or Bedrock creds),
   `/ask` returns an extractive answer. The owner must plug in a key.
7. **Legal scope of "authority".** Publications are not binding authority;
   we keep an `authority_weight` (form/instructions 1.0, publication 0.8,
   FAQ 0.5) and surface the distinction in conflicts, but the policy is a
   judgment call for the owner.
8. **Embedding model drift.** Changing `TAXRAG_EMBED_MODEL` requires
   `taxrag reindex --embeddings`; vectors are tagged with model name so mixed
   states are detected and refused.
9. **Gold set size.** The initial gold set is ~40 items written by the
   builder, not yet reviewed by a tax analyst. It needs owner review before
   the metrics are trusted.
10. **Access to the live DynamoDB/S3.** The build environment had no
    credentials for the owner's account; the adapter was validated against
    the JSON export committed in IRS-Forms. Live mode is one env var away.
