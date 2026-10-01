# Things to plug in later

Everything below was either unavailable in the build environment or is a decision
only you can make. The system runs without all of them.

## 1. LLM for synthesized answers (optional but recommended)
* `export ANTHROPIC_API_KEY=...` → `/ask` research/taxdev/compare modes produce
  synthesized answers with per-claim citations and quote validation.
  Model: `TAXRAG_LLM_MODEL` (default `claude-sonnet-5-5`).
* Or Bedrock (what `IRS-Forms/ai_summary.py` already uses):
  `TAXRAG_LLM_PROVIDER=bedrock TAXRAG_BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-5-5` + AWS creds.
* Without either, answers are **extractive** (verbatim passages, labelled as such). Search, source, evidence,
  compare-with-diffs, citations and the UI all work.

## 2. Existing IRS-Forms pipeline as upstream (DynamoDB `Forms` + S3 `forms123456`)
* The adapter `taxrag/adapters/irs_pipeline.py` is validated against the JSON export in the IRS-Forms repo
  (`ezya7xfym45tteatsyctr5iysa.json`). To run it:
  ```bash
  taxrag ingest irs_pipeline --export /path/to/ezya7xfym45tteatsyctr5iysa.json --years 2024,2025
  ```
* Live mode needs AWS credentials with `dynamodb:Scan` on table `Forms` and `s3:GetObject` on `forms123456`
  (`TAXRAG_IRS_DYNAMO_TABLE`, `TAXRAG_IRS_S3_BUCKET`, `TAXRAG_IRS_AWS_REGION`). Pass `use_s3=True` to read the archived
  PDFs instead of re-downloading from irs.gov. Note the archive stores *watermark-stripped* drafts (cover page removed);
  the RAG keeps citing original page numbers, so for drafts it prefers the irs.gov original when reachable.
* Recommended wiring: have the Lambda `New_IRS_Forms` publish each new row to SQS/EventBridge, and run
  `taxrag ingest irs_pipeline` (or `POST /admin/ingest/irs_pipeline`) on that event. Until then a nightly cron works.
* Rotate the SQL Server `sa` password committed in `IRS-Forms/IRS Forms/setupdb.py` (flagged in that repo's README).

## 3. Arkansas (and other bot-protected state sites)
* `dfa.arkansas.gov` returns HTTP 403 to non-browser clients. Options:
  (a) fetch with the pre-installed Playwright/Chromium (`taxrag/collectors/arkansas.py` has the hook),
  (b) drop PDFs into `data/inbox/arkansas/` and add them to `taxrag/collectors/seeds/arkansas.yaml`,
  (c) ask DFA for a bulk-download arrangement.
* Decide the crawling posture per state (rate limits, UA string in `TAXRAG_HTTP_USER_AGENT`).

## 4. OCR
* No tesseract in the build container. `pip install pytesseract` + `apt install tesseract-ocr` and pass `ocr=True`
  to `extract_pdf`; pages with no text layer are already flagged (`document_versions.needs_ocr`).

## 5. Human review of the gold set
* `taxrag/eval/gold.yaml` has 40 questions written by the builder, **not yet reviewed by a tax analyst**.
  Review expected documents/sections/pages, add real analyst questions, then re-run `taxrag evaluate`.

## 6. Scale-out storage (when the corpus passes ~500k chunks or needs multi-user writes)
* Postgres + pgvector: see `docs/POSTGRES_MIGRATION.md`. The schema is portable; only `fts_search` and `vector_search`
  in `taxrag/store/sqlite.py` need a Postgres implementation.
* OpenSearch for BM25 at >5M chunks.

## 7. Scheduling / refresh
* Any scheduler works because ingestion is idempotent: cron `taxrag ingest all --live`, GitHub Actions
  (like `auto-blog.yml`), or EventBridge → ECS task. Suggested: nightly for drafts during Jul–Jan, weekly otherwise.

## 8. Auth in front of the API
* None included. Reuse the Cognito user pool from the `tax-assistant` backend or put the FastAPI app behind an ALB with OIDC.

## 9. Internal TaxDev knowledge
* Collector interface supports `provenance_class=INTERNAL_TAXDEV`; implement a collector for your internal
  docs (Confluence/SharePoint/ADO exports) and pass `include_internal=true` on `/ask`. Internal passages are never
  rendered as government authority (hard filter + `INTERNAL:` citation prefix).

## 10. Repo placement
* Built inside `taylor-riley-portfolio/tax-rag/` because that was the session's repository. It is self-contained;
  `git subtree split -P tax-rag` moves it to its own repo. `.assetsignore` excludes it from the Cloudflare deploy.
