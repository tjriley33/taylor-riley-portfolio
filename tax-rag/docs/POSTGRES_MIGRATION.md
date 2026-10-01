# Moving the store to Postgres + pgvector

The SQLite store is the development/single-node default. The schema in
`taxrag/store/schema.sql` is portable SQL except for two things:

| SQLite | Postgres equivalent |
|---|---|
| `chunk_fts` FTS5 virtual table, `bm25()` | `ALTER TABLE chunks ADD COLUMN tsv tsvector GENERATED ALWAYS AS (setweight(to_tsvector('english', identifiers),'A') \|\| setweight(to_tsvector('english', path_text),'B') \|\| to_tsvector('english', text)) STORED;` + GIN index; rank with `ts_rank_cd`. For true BM25 use the `pg_search` (ParadeDB) extension or OpenSearch. |
| `embeddings.vector BLOB` + numpy scan | `vector(384)` column (pgvector) with `CREATE INDEX ... USING hnsw (vector vector_cosine_ops)`; partial indexes per `provenance_class`. Filter-first is preserved by putting the metadata predicates in the same query: `WHERE jurisdiction=$1 AND tax_year=$2 ORDER BY vector <=> $3 LIMIT 60`. |
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGSERIAL` |
| `json` stored as TEXT | `jsonb` |

Implementation: subclass `taxrag.store.sqlite.Store` as `PgStore`, override
`conn()` (psycopg pool), `fts_search`, `vector_search`, `replace_chunks`
(no FTS mirror table) and `replace_embeddings`. Everything else is plain SQL
that runs unchanged. Keep `filter_sql()` as the single place compound filters
are built so the compound index `(provenance_class, jurisdiction, tax_year,
form_number, document_type, draft_or_final)` is used by both engines.

Sizing: ~10M chunks × 384 float32 ≈ 15 GB of vectors + HNSW ≈ 20 GB; an
`r6g.large` RDS instance handles Phase 6 scale. Raw PDFs stay in S3
(`s3://<bucket>/raw/<sha256>.pdf`), referenced by `document_versions.file_path`.
