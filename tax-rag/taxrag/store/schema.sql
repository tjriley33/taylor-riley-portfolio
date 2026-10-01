-- taxrag storage schema (SQLite dialect; portable SQL except FTS5 and BLOB vectors)

CREATE TABLE IF NOT EXISTS documents (
  document_id        TEXT PRIMARY KEY,
  authority          TEXT NOT NULL,
  jurisdiction       TEXT NOT NULL,
  agency             TEXT NOT NULL,
  document_type      TEXT NOT NULL,
  form_number        TEXT,
  form_name          TEXT,
  schedule           TEXT,
  publication_number TEXT,
  tax_type           TEXT NOT NULL DEFAULT '[]',   -- JSON list
  title              TEXT,
  provenance_class   TEXT NOT NULL DEFAULT 'PUBLIC_AUTHORITY',
  created_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_documents_lookup ON documents(jurisdiction, document_type, form_number, schedule, publication_number);

CREATE TABLE IF NOT EXISTS document_versions (
  version_id             TEXT PRIMARY KEY,          -- sha256 of file bytes
  document_id            TEXT NOT NULL REFERENCES documents(document_id),
  tax_year               INTEGER,
  revision               TEXT,
  revision_date          TEXT,
  release_date           TEXT,
  draft_or_final         TEXT NOT NULL,             -- draft | final
  effective_date         TEXT,
  source_url             TEXT NOT NULL,
  download_url           TEXT NOT NULL,
  retrieved_at           TEXT NOT NULL,
  file_hash              TEXT NOT NULL,
  file_path              TEXT NOT NULL,
  page_count             INTEGER NOT NULL DEFAULT 0,
  supersedes_version_id  TEXT,
  status                 TEXT NOT NULL DEFAULT 'current',   -- current | superseded | withdrawn
  ingest_state           TEXT NOT NULL DEFAULT 'downloaded',
  title_in_pdf           TEXT,
  pdf_metadata           TEXT NOT NULL DEFAULT '{}',
  upstream               TEXT NOT NULL DEFAULT '{}',
  needs_ocr              INTEGER NOT NULL DEFAULT 0,
  quarantined            INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_versions_doc ON document_versions(document_id, tax_year, draft_or_final, status);
CREATE INDEX IF NOT EXISTS ix_versions_url ON document_versions(download_url);

CREATE TABLE IF NOT EXISTS sections (
  section_id         TEXT PRIMARY KEY,
  version_id         TEXT NOT NULL REFERENCES document_versions(version_id),
  parent_section_id  TEXT,
  level              INTEGER NOT NULL,
  heading            TEXT NOT NULL,
  path               TEXT NOT NULL,                 -- JSON list
  path_text          TEXT NOT NULL,
  kind               TEXT NOT NULL DEFAULT 'section',
  line_ref           TEXT,
  page_start         INTEGER NOT NULL,
  page_end           INTEGER NOT NULL,
  ordinal            INTEGER NOT NULL,
  text               TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sections_version ON sections(version_id, ordinal);
CREATE INDEX IF NOT EXISTS ix_sections_path ON sections(version_id, path_text);

CREATE TABLE IF NOT EXISTS chunks (
  chunk_id         TEXT PRIMARY KEY,
  version_id       TEXT NOT NULL REFERENCES document_versions(version_id),
  section_id       TEXT,
  parent_chunk_id  TEXT,
  ordinal          INTEGER NOT NULL,
  text             TEXT NOT NULL,
  text_hash        TEXT NOT NULL,
  token_count      INTEGER NOT NULL,
  page_start       INTEGER NOT NULL,
  page_end         INTEGER NOT NULL,
  path_text        TEXT NOT NULL,
  kind             TEXT NOT NULL,
  line_refs        TEXT NOT NULL DEFAULT '[]',
  identifiers      TEXT NOT NULL DEFAULT '',
  strategy         TEXT NOT NULL,
  -- denormalized filter columns
  document_id      TEXT NOT NULL,
  authority        TEXT NOT NULL,
  jurisdiction     TEXT NOT NULL,
  tax_year         INTEGER,
  form_number      TEXT,
  schedule         TEXT,
  publication_number TEXT,
  document_type    TEXT NOT NULL,
  draft_or_final   TEXT NOT NULL,
  version_status   TEXT NOT NULL,
  provenance_class TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_chunks_filter ON chunks(strategy, provenance_class, jurisdiction, tax_year, form_number, document_type, draft_or_final);
CREATE INDEX IF NOT EXISTS ix_chunks_version ON chunks(version_id, ordinal);
CREATE INDEX IF NOT EXISTS ix_chunks_section ON chunks(section_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
  chunk_id UNINDEXED,
  text,
  path_text,
  identifiers,
  tokenize = 'porter unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS embeddings (
  chunk_id   TEXT PRIMARY KEY REFERENCES chunks(chunk_id),
  model      TEXT NOT NULL,
  dim        INTEGER NOT NULL,
  vector     BLOB NOT NULL,
  strategy   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_embeddings_model ON embeddings(model, strategy);

CREATE TABLE IF NOT EXISTS relationships (
  rel_id           INTEGER PRIMARY KEY AUTOINCREMENT,
  src_type         TEXT NOT NULL,
  src_id           TEXT NOT NULL,
  rel_type         TEXT NOT NULL,
  dst_type         TEXT NOT NULL,
  dst_id           TEXT,
  dst_label        TEXT NOT NULL,
  dst_jurisdiction TEXT,
  confidence       REAL NOT NULL DEFAULT 1.0,
  evidence_page    INTEGER,
  version_id       TEXT
);
CREATE INDEX IF NOT EXISTS ix_rel_src ON relationships(src_id, rel_type);
CREATE INDEX IF NOT EXISTS ix_rel_dst ON relationships(dst_id, rel_type);
CREATE INDEX IF NOT EXISTS ix_rel_version ON relationships(version_id);

CREATE TABLE IF NOT EXISTS document_changes (
  change_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  old_version_id   TEXT NOT NULL,
  new_version_id   TEXT NOT NULL,
  change_type      TEXT NOT NULL,      -- section_added | section_removed | section_modified | line_changed | table_changed | reference_changed
  old_section_id   TEXT,
  new_section_id   TEXT,
  path_text        TEXT NOT NULL,
  old_page         INTEGER,
  new_page         INTEGER,
  similarity       REAL,
  diff_text        TEXT,
  summary          TEXT
);
CREATE INDEX IF NOT EXISTS ix_changes_pair ON document_changes(old_version_id, new_version_id);
CREATE INDEX IF NOT EXISTS ix_changes_path ON document_changes(path_text);

CREATE TABLE IF NOT EXISTS citations (
  citation_id  TEXT PRIMARY KEY,
  query_id     TEXT NOT NULL,
  chunk_id     TEXT NOT NULL,
  version_id   TEXT NOT NULL,
  section_id   TEXT,
  page         INTEGER,
  line_ref     TEXT,
  quote        TEXT,
  label        TEXT,
  validated    INTEGER NOT NULL DEFAULT 0,
  validation_notes TEXT
);
CREATE INDEX IF NOT EXISTS ix_citations_query ON citations(query_id);

CREATE TABLE IF NOT EXISTS ingestion_runs (
  run_id       TEXT PRIMARY KEY,
  collector    TEXT NOT NULL,
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  status       TEXT NOT NULL,
  stats        TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS ingestion_items (
  item_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id       TEXT NOT NULL,
  version_id   TEXT,
  download_url TEXT,
  stage        TEXT NOT NULL,
  status       TEXT NOT NULL,          -- ok | skipped | failed | quarantined
  error        TEXT,
  attempts     INTEGER NOT NULL DEFAULT 1,
  ts           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_items_version ON ingestion_items(version_id, stage);

CREATE TABLE IF NOT EXISTS query_log (
  query_id          TEXT PRIMARY KEY,
  ts                TEXT NOT NULL,
  mode              TEXT NOT NULL,
  question          TEXT NOT NULL,
  parsed            TEXT NOT NULL DEFAULT '{}',
  filters           TEXT NOT NULL DEFAULT '{}',
  candidates        TEXT NOT NULL DEFAULT '[]',
  context_chunk_ids TEXT NOT NULL DEFAULT '[]',
  citations         TEXT NOT NULL DEFAULT '[]',
  answer            TEXT NOT NULL DEFAULT '{}',
  latency_ms        TEXT NOT NULL DEFAULT '{}',
  model             TEXT,
  embed_model       TEXT,
  tokens            TEXT NOT NULL DEFAULT '{}',
  confidence        REAL,
  failure           TEXT,
  feedback          TEXT
);

CREATE TABLE IF NOT EXISTS evaluation_questions (
  qid                 TEXT PRIMARY KEY,
  category            TEXT NOT NULL,
  question            TEXT NOT NULL,
  mode                TEXT NOT NULL DEFAULT 'research',
  expected            TEXT NOT NULL,     -- JSON
  reviewer            TEXT,
  notes               TEXT
);

CREATE TABLE IF NOT EXISTS evaluation_results (
  result_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id      TEXT NOT NULL,
  qid         TEXT NOT NULL,
  strategy    TEXT NOT NULL,
  metrics     TEXT NOT NULL,            -- JSON
  latency_ms  REAL,
  ts          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_eval_run ON evaluation_results(run_id);
