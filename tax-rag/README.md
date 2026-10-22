# TaxRAG — citation-first federal + state tax research system

A retrieval system over authoritative IRS and state Department of Revenue documents
(forms, instructions, schedules, publications, e-file specs) that answers tax
questions **only** from retrieved authority and tells you exactly which agency,
document, tax year, revision, draft/final status, section, line and page supports
each statement.

Guiding principle: *"Can a tax analyst prove where this answer came from?"*

Architecture, data model, component choices and the phased plan are in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Things you still need to supply
(API keys, AWS access, bot-blocked states) are in [`PLUG_IN_LATER.md`](PLUG_IN_LATER.md).

## Quick start

```bash
cd tax-rag
python3.11 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"            # or: uv pip install -e ".[dev]"

# Use the prebuilt index shipped in dist/ (59 documents / 79 versions, built 2026-10-01).
# This unpacks it, re-downloads the original PDFs from irs.gov / state sites (hash-verified,
# ~70 MB, a minute or two) so citations can open the source page, and prints stats:
make pull-index                     # == gunzip dist/taxrag-index-*.sqlite.gz > data/taxrag.sqlite && taxrag fetch-raw

taxrag stats
taxrag ask "2025 Form 1040 instructions line 1a wages"
taxrag serve                        # UI + API at http://localhost:8000  (docs at /docs)

# Or rebuild the index from scratch (seeds only, ~75 min on 4 CPU cores, no API keys needed):
taxrag ingest all                   # IRS + Virginia + New York + Wisconsin seed corpora
taxrag ingest irs --live            # also crawl irs.gov current/draft listing pages
```

Everything except LLM-synthesized prose runs locally with no keys: embeddings
(`BAAI/bge-small-en-v1.5`) and the cross-encoder reranker are ONNX models
downloaded once from Hugging Face into `data/models/`.

Set `ANTHROPIC_API_KEY` (or `TAXRAG_LLM_PROVIDER=bedrock` with AWS credentials)
to get synthesized answers. Without a key, `ask` returns an **extractive**
answer: verbatim passages with citations, clearly labelled.

## CLI

| Command | Purpose |
|---|---|
| `taxrag ingest <irs|virginia|new_york|wisconsin|arkansas|irs_pipeline|all> [--live] [--limit N] [--years 2024,2025]` | Idempotent discover → download → hash → parse → chunk → embed → index → diff |
| `taxrag ingest irs_pipeline --export path/to/dynamo.jsonl` | Feed from the existing IRS-Forms pipeline export (or live DynamoDB/S3 with AWS creds) |
| `taxrag ask "question" [--mode research|taxdev|source|compare|evidence] [--jurisdiction VA] [--tax-year 2025] [--drafts draft|final] [--json-out]` | Query |
| `taxrag diff <old_version_id> <new_version_id> [--path "Line 1a"]` | Section-level changes between two versions |
| `taxrag evaluate [--strategy hier_v1|fixed_512|page_v1] [--report out.json]` | Run the gold-set evaluation |
| `taxrag reindex [--strategies hier_v1,fixed_512] [--embeddings-only] [--reparse]` | Rebuild chunks/embeddings after code or model changes |
| `taxrag rediff` | Recompute all stored section diffs (after a parser change) |
| `taxrag fetch-raw` | Re-download original PDFs by hash for every indexed version |
| `taxrag sync push|pull` | Index + originals to/from S3 (`TAXRAG_S3_BUCKET`) |
| `taxrag docs`, `taxrag stats`, `taxrag quarantine [--release VID]`, `taxrag debug <query_id>` | Inspection |
| `taxrag serve [--port 8000]` | API + analyst UI |

## API

`POST /search` · `POST /ask` · `POST /compare` · `GET /documents` · `GET /documents/{id}` ·
`GET /documents/{id}/versions` · `GET /versions/{id}/sections` · `GET /sections/{id}` ·
`GET /chunks/{id}` · `GET /sources/{citation_or_chunk_id}` · `GET /files/{version_id}.pdf` ·
`GET /changes?old=&new=` · `GET /graph/{document_id}` · `GET /queries/{query_id}` (debug: why each chunk was retrieved) ·
`POST /feedback` · `GET /meta/filters` · `GET /admin/stats` · `GET /admin/runs` · `POST /admin/reindex` · `POST /admin/ingest/{collector}`

Every response is structured JSON: parsed query, filters actually applied, any
relaxations, confidence, `sufficient_evidence`, evidence passages with per-chunk
scores and retrieval reasons, validated citations, detected conflicts, and (for
compare) stored section diffs with links to both PDF pages.

Example:

```bash
curl -s localhost:8000/ask -H 'content-type: application/json' \
  -d '{"query":"What is Wisconsin Schedule I for 2025?","mode":"research"}' | jq '.citations[].rendered'
```

## Answer modes

* **research** — answer with citations; each claim labelled `explicit` / `derived` / `not_established`.
* **taxdev** — same, drafts allowed, emphasis on line/calculation/dependency changes.
* **source** — passages only, no synthesis.
* **compare** — two tax years (or draft vs final); retrieves both sides deliberately and attaches stored `document_changes`.
* **evidence** — the exact bundle (system + user prompt) an LLM would receive, for audit.

## Safeguards

Filter-first retrieval (jurisdiction / year / draft status / provenance class are
SQL filters, not similarity hints); deterministic tax-aware reranking with hard
demotion of wrong-state / wrong-year passages; relevance floor → "insufficient
evidence" instead of a guess; citation validator rejects ids not in the context
and verifies quotes against the passage; conflict detector surfaces federal vs
state / year vs year / draft vs final / publication vs instructions pairs without
resolving them; `PUBLIC_AUTHORITY` vs `INTERNAL_TAXDEV` provenance is a hard
filter and internal passages are labelled `INTERNAL:` in citations.

## Layout

See section 14 of `docs/ARCHITECTURE.md`. Tests: `pytest`.

## Data

`data/raw/<sha256>.pdf` — immutable originals (every citation points at one of these by hash).
`data/taxrag.sqlite` — the entire structured store (documents, versions, sections, chunks,
FTS5 index, embeddings, relationships, changes, ingestion runs, query log, eval results).
