"""SQLite implementation of the structured store.

The schema is portable; the only SQLite-specific parts are FTS5 and storing
vectors as float32 BLOBs. A Postgres implementation would subclass Store and
override `fts_search` (tsvector) and `vector_search` (pgvector).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np

from ..models import ChunkRecord, DocumentIdentity, Relationship, SectionNode, VersionRecord, utcnow

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

FILTER_COLUMNS = {
    "jurisdiction": "jurisdiction",
    "tax_year": "tax_year",
    "form_number": "form_number",
    "schedule": "schedule",
    "publication_number": "publication_number",
    "document_type": "document_type",
    "draft_or_final": "draft_or_final",
    "authority": "authority",
    "document_id": "document_id",
    "version_id": "version_id",
    "version_status": "version_status",
    "provenance_class": "provenance_class",
    "strategy": "strategy",
}


def _json(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._vec_cache: dict[str, tuple[list[str], np.ndarray]] = {}
        self._vec_cache_lock = threading.Lock()
        with self.conn() as c:
            c.executescript(SCHEMA_PATH.read_text())

    # ------------------------------------------------------------------ conn
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, check_same_thread=False, timeout=60)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA foreign_keys=OFF")
            self._local.conn = c
        return c

    def q(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return self.conn().execute(sql, tuple(params)).fetchall()

    def q1(self, sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
        return self.conn().execute(sql, tuple(params)).fetchone()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self.conn() as c:
            c.execute(sql, tuple(params))

    # ------------------------------------------------------------- documents
    def upsert_document(self, ident: DocumentIdentity) -> str:
        did = ident.document_id
        row = self.q1("SELECT document_id, title, form_name FROM documents WHERE document_id=?", (did,))
        if row is None:
            self.execute(
                "INSERT INTO documents(document_id, authority, jurisdiction, agency, document_type, form_number, form_name,"
                " schedule, publication_number, tax_type, title, provenance_class, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (did, ident.authority, ident.jurisdiction, ident.agency, ident.document_type.value, ident.form_number,
                 ident.form_name, ident.schedule, ident.publication_number, _json(ident.tax_type), ident.title,
                 ident.provenance_class.value, utcnow()),
            )
        else:
            # fill blanks only; never clobber
            if ident.title and not row["title"]:
                self.execute("UPDATE documents SET title=? WHERE document_id=?", (ident.title, did))
            if ident.form_name and not row["form_name"]:
                self.execute("UPDATE documents SET form_name=? WHERE document_id=?", (ident.form_name, did))
            if ident.tax_type:
                self.execute("UPDATE documents SET tax_type=? WHERE document_id=?", (_json(ident.tax_type), did))
        return did

    def get_document(self, document_id: str) -> Optional[dict]:
        r = self.q1("SELECT * FROM documents WHERE document_id=?", (document_id,))
        return dict(r) if r else None

    def find_documents(self, jurisdiction: str | None = None, document_type: str | None = None,
                       form_number: str | None = None, schedule: str | None = None,
                       publication_number: str | None = None) -> list[dict]:
        sql, params = "SELECT * FROM documents WHERE 1=1", []
        for col, val in [("jurisdiction", jurisdiction), ("document_type", document_type), ("form_number", form_number),
                         ("schedule", schedule), ("publication_number", publication_number)]:
            if val is not None:
                sql += f" AND upper({col})=upper(?)"
                params.append(val)
        return [dict(r) for r in self.q(sql, params)]

    # -------------------------------------------------------------- versions
    def get_version(self, version_id: str) -> Optional[dict]:
        r = self.q1("SELECT * FROM document_versions WHERE version_id=?", (version_id,))
        return self._version_row(r) if r else None

    def _version_row(self, r: sqlite3.Row) -> dict:
        d = dict(r)
        d["pdf_metadata"] = json.loads(d.get("pdf_metadata") or "{}")
        d["upstream"] = json.loads(d.get("upstream") or "{}")
        return d

    def versions_for_document(self, document_id: str) -> list[dict]:
        rows = self.q("SELECT * FROM document_versions WHERE document_id=? ORDER BY tax_year DESC, revision DESC, retrieved_at DESC", (document_id,))
        return [self._version_row(r) for r in rows]

    def version_by_url_current(self, download_url: str) -> Optional[dict]:
        r = self.q1("SELECT * FROM document_versions WHERE download_url=? AND status='current' ORDER BY retrieved_at DESC LIMIT 1", (download_url,))
        return self._version_row(r) if r else None

    def insert_version(self, v: VersionRecord) -> None:
        self.execute(
            "INSERT INTO document_versions(version_id, document_id, tax_year, revision, revision_date, release_date, draft_or_final,"
            " effective_date, source_url, download_url, retrieved_at, file_hash, file_path, page_count, supersedes_version_id, status,"
            " ingest_state, title_in_pdf, pdf_metadata, upstream) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (v.version_id, v.document_id, v.tax_year, v.revision, v.revision_date, v.release_date, v.draft_or_final,
             v.effective_date, v.source_url, v.download_url, v.retrieved_at, v.file_hash, v.file_path, v.page_count,
             v.supersedes_version_id, v.status, v.ingest_state, v.title_in_pdf, _json(v.pdf_metadata), _json(v.upstream)),
        )

    def update_version(self, version_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        vals = [(_json(v) if isinstance(v, (dict, list)) else v) for v in fields.values()]
        self.execute(f"UPDATE document_versions SET {cols} WHERE version_id=?", (*vals, version_id))
        if "status" in fields or "draft_or_final" in fields:
            self.execute("UPDATE chunks SET version_status=(SELECT status FROM document_versions WHERE version_id=?) WHERE version_id=?", (version_id, version_id))

    def supersede(self, old_version_id: str, new_version_id: str) -> None:
        self.update_version(old_version_id, status="superseded")
        self.update_version(new_version_id, supersedes_version_id=old_version_id)

    def recompute_current_status(self, document_id: str) -> None:
        """Within (document, tax_year|revision, draft_or_final) the newest retrieved version is current."""
        rows = self.versions_for_document(document_id)
        groups: dict[tuple, list[dict]] = {}
        for v in rows:
            groups.setdefault((v["tax_year"], v["revision"], v["draft_or_final"]), []).append(v)
        for key, vs in groups.items():
            vs.sort(key=lambda v: (v["release_date"] or "", v["retrieved_at"]), reverse=True)
            for i, v in enumerate(vs):
                status = "current" if i == 0 else "superseded"
                if v["status"] != status and v["status"] != "withdrawn":
                    self.update_version(v["version_id"], status=status)
                if i + 1 < len(vs) and not v.get("supersedes_version_id"):
                    self.update_version(v["version_id"], supersedes_version_id=vs[i + 1]["version_id"])

    def resolve_versions(self, document_id: str, tax_year: int | None = None, draft_or_final: str | None = None,
                         status: str = "current") -> list[dict]:
        sql, params = "SELECT * FROM document_versions WHERE document_id=?", [document_id]
        if tax_year is not None:
            sql += " AND tax_year=?"; params.append(tax_year)
        if draft_or_final:
            sql += " AND draft_or_final=?"; params.append(draft_or_final)
        if status:
            sql += " AND status=?"; params.append(status)
        sql += " ORDER BY tax_year DESC, release_date DESC, retrieved_at DESC"
        return [self._version_row(r) for r in self.q(sql, params)]

    def available_years(self, document_id: str) -> list[dict]:
        return [dict(r) for r in self.q(
            "SELECT tax_year, draft_or_final, status, count(*) n FROM document_versions WHERE document_id=? GROUP BY 1,2,3 ORDER BY 1 DESC", (document_id,))]

    # -------------------------------------------------------------- sections
    def replace_sections(self, version_id: str, sections: list[SectionNode]) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM sections WHERE version_id=?", (version_id,))
            c.executemany(
                "INSERT INTO sections(section_id, version_id, parent_section_id, level, heading, path, path_text, kind, line_ref,"
                " page_start, page_end, ordinal, text) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(s.section_id, s.version_id, s.parent_section_id, s.level, s.heading, _json(s.path), s.path_text, s.kind,
                  s.line_ref, s.page_start, s.page_end, s.ordinal, s.text) for s in sections],
            )

    def sections_for_version(self, version_id: str) -> list[dict]:
        return [dict(r) for r in self.q("SELECT * FROM sections WHERE version_id=? ORDER BY ordinal", (version_id,))]

    def get_section(self, section_id: str) -> Optional[dict]:
        r = self.q1("SELECT * FROM sections WHERE section_id=?", (section_id,))
        return dict(r) if r else None

    # ---------------------------------------------------------------- chunks
    def replace_chunks(self, version_id: str, strategy: str, chunks: list[ChunkRecord], version: dict, document: dict) -> None:
        with self.conn() as c:
            old = [r[0] for r in c.execute("SELECT chunk_id FROM chunks WHERE version_id=? AND strategy=?", (version_id, strategy))]
            if old and set(old) == {ch.chunk_id for ch in chunks}:
                return  # identical chunk set (ids are content-derived): keep rows, FTS and embeddings
            if old:
                c.executemany("DELETE FROM chunk_fts WHERE chunk_id=?", [(o,) for o in old])
                c.executemany("DELETE FROM embeddings WHERE chunk_id=?", [(o,) for o in old])
                c.execute("DELETE FROM chunks WHERE version_id=? AND strategy=?", (version_id, strategy))
            import hashlib
            rows = []
            for ch in chunks:
                rows.append((
                    ch.chunk_id, ch.version_id, ch.section_id, ch.parent_chunk_id, ch.ordinal, ch.text,
                    hashlib.sha1(ch.text.encode()).hexdigest(), ch.token_count, ch.page_start, ch.page_end, ch.path_text,
                    ch.kind, _json(ch.line_refs), ch.identifiers, ch.strategy,
                    document["document_id"], document["authority"], document["jurisdiction"], version["tax_year"],
                    document["form_number"], document["schedule"], document["publication_number"], document["document_type"],
                    version["draft_or_final"], version["status"], document["provenance_class"],
                ))
            c.executemany(
                "INSERT INTO chunks(chunk_id, version_id, section_id, parent_chunk_id, ordinal, text, text_hash, token_count,"
                " page_start, page_end, path_text, kind, line_refs, identifiers, strategy, document_id, authority, jurisdiction,"
                " tax_year, form_number, schedule, publication_number, document_type, draft_or_final, version_status, provenance_class)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            c.executemany("INSERT INTO chunk_fts(chunk_id, text, path_text, identifiers) VALUES (?,?,?,?)",
                          [(ch.chunk_id, ch.text, ch.path_text, ch.identifiers) for ch in chunks])
        self._invalidate_vec_cache()

    def get_chunk(self, chunk_id: str) -> Optional[dict]:
        r = self.q1("SELECT * FROM chunks WHERE chunk_id=?", (chunk_id,))
        return self._chunk_row(r) if r else None

    def get_chunks(self, chunk_ids: list[str]) -> dict[str, dict]:
        if not chunk_ids:
            return {}
        out: dict[str, dict] = {}
        for i in range(0, len(chunk_ids), 500):
            batch = chunk_ids[i:i + 500]
            rows = self.q(f"SELECT * FROM chunks WHERE chunk_id IN ({','.join('?' * len(batch))})", batch)
            for r in rows:
                out[r["chunk_id"]] = self._chunk_row(r)
        return out

    def _chunk_row(self, r: sqlite3.Row) -> dict:
        d = dict(r)
        d["line_refs"] = json.loads(d.get("line_refs") or "[]")
        return d

    def chunks_for_version(self, version_id: str, strategy: str) -> list[dict]:
        return [self._chunk_row(r) for r in self.q("SELECT * FROM chunks WHERE version_id=? AND strategy=? ORDER BY ordinal", (version_id, strategy))]

    def chunks_for_section(self, section_id: str, strategy: str) -> list[dict]:
        return [self._chunk_row(r) for r in self.q("SELECT * FROM chunks WHERE section_id=? AND strategy=? ORDER BY ordinal", (section_id, strategy))]

    def neighbor_chunks(self, chunk: dict, radius: int = 1) -> list[dict]:
        return [self._chunk_row(r) for r in self.q(
            "SELECT * FROM chunks WHERE version_id=? AND strategy=? AND ordinal BETWEEN ? AND ? ORDER BY ordinal",
            (chunk["version_id"], chunk["strategy"], chunk["ordinal"] - radius, chunk["ordinal"] + radius))]

    # --------------------------------------------------------------- filters
    @staticmethod
    def filter_sql(filters: dict[str, Any], alias: str = "c") -> tuple[str, list[Any]]:
        """Compound filter -> SQL. Values may be scalars or lists (IN). None values are skipped."""
        clauses, params = [], []
        for key, val in (filters or {}).items():
            col = FILTER_COLUMNS.get(key)
            if col is None or val is None:
                continue
            if isinstance(val, (list, tuple, set)):
                vals = [v for v in val if v is not None]
                if not vals:
                    continue
                clauses.append(f"upper(CAST({alias}.{col} AS TEXT)) IN ({','.join('?' * len(vals))})")
                params.extend(str(v).upper() for v in vals)
            else:
                clauses.append(f"upper(CAST({alias}.{col} AS TEXT))=upper(?)")
                params.append(str(val))
        return (" AND ".join(clauses) if clauses else "1=1"), params

    def count_chunks(self, filters: dict[str, Any]) -> int:
        where, params = self.filter_sql(filters)
        return self.q1(f"SELECT count(*) n FROM chunks c WHERE {where}", params)["n"]

    def filtered_chunk_ids(self, filters: dict[str, Any]) -> list[str]:
        where, params = self.filter_sql(filters)
        return [r[0] for r in self.q(f"SELECT chunk_id FROM chunks c WHERE {where}", params)]

    # ------------------------------------------------------------------ FTS
    def fts_search(self, query: str, filters: dict[str, Any], k: int = 50) -> list[tuple[str, float]]:
        """BM25 search. Returns (chunk_id, score) with higher = better."""
        if not query.strip():
            return []
        where, params = self.filter_sql(filters)
        sql = (
            "SELECT f.chunk_id, bm25(chunk_fts, 0, 1.0, 2.0, 4.0) AS rank FROM chunk_fts f "
            f"JOIN chunks c ON c.chunk_id=f.chunk_id WHERE chunk_fts MATCH ? AND {where} ORDER BY rank LIMIT ?"
        )
        try:
            rows = self.q(sql, [query, *params, k])
        except sqlite3.OperationalError:
            return []
        return [(r["chunk_id"], -float(r["rank"])) for r in rows]

    # -------------------------------------------------------------- vectors
    def replace_embeddings(self, items: list[tuple[str, np.ndarray]], model: str, strategy: str) -> None:
        with self.conn() as c:
            c.executemany(
                "INSERT OR REPLACE INTO embeddings(chunk_id, model, dim, vector, strategy) VALUES (?,?,?,?,?)",
                [(cid, model, int(vec.shape[0]), np.asarray(vec, dtype=np.float32).tobytes(), strategy) for cid, vec in items],
            )
        self._invalidate_vec_cache()

    def missing_embeddings(self, version_id: str, strategy: str, model: str) -> list[dict]:
        return [self._chunk_row(r) for r in self.q(
            "SELECT c.* FROM chunks c LEFT JOIN embeddings e ON e.chunk_id=c.chunk_id AND e.model=? "
            "WHERE c.version_id=? AND c.strategy=? AND e.chunk_id IS NULL ORDER BY c.ordinal", (model, version_id, strategy))]

    def _invalidate_vec_cache(self) -> None:
        with self._vec_cache_lock:
            self._vec_cache.clear()

    def _vectors(self, model: str, strategy: str) -> tuple[list[str], np.ndarray]:
        key = f"{model}|{strategy}"
        with self._vec_cache_lock:
            if key in self._vec_cache:
                return self._vec_cache[key]
            rows = self.q("SELECT chunk_id, dim, vector FROM embeddings WHERE model=? AND strategy=?", (model, strategy))
            ids = [r["chunk_id"] for r in rows]
            if rows:
                mat = np.vstack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
                norms = np.linalg.norm(mat, axis=1, keepdims=True)
                norms[norms == 0] = 1
                mat = mat / norms
            else:
                mat = np.zeros((0, 1), dtype=np.float32)
            self._vec_cache[key] = (ids, mat)
            return ids, mat

    def vector_search(self, qvec: np.ndarray, filters: dict[str, Any], model: str, strategy: str, k: int = 50) -> list[tuple[str, float]]:
        """Filter-first exact cosine search."""
        ids, mat = self._vectors(model, strategy)
        if not ids:
            return []
        allowed = set(self.filtered_chunk_ids({**filters, "strategy": strategy}))
        if not allowed:
            return []
        mask = np.fromiter((cid in allowed for cid in ids), dtype=bool, count=len(ids))
        idx = np.nonzero(mask)[0]
        if idx.size == 0:
            return []
        q = np.asarray(qvec, dtype=np.float32)
        q = q / (np.linalg.norm(q) or 1.0)
        sims = mat[idx] @ q
        top = np.argsort(-sims)[:k]
        return [(ids[idx[i]], float(sims[i])) for i in top]

    # --------------------------------------------------------- relationships
    def replace_relationships(self, version_id: str, rels: list[Relationship]) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM relationships WHERE version_id=?", (version_id,))
            c.executemany(
                "INSERT INTO relationships(src_type, src_id, rel_type, dst_type, dst_id, dst_label, dst_jurisdiction, confidence, evidence_page, version_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(r.src_type, r.src_id, r.rel_type, r.dst_type, r.dst_id, r.dst_label, r.dst_jurisdiction, r.confidence,
                  r.evidence_page, version_id) for r in rels])

    def relationships_from(self, src_ids: list[str]) -> list[dict]:
        if not src_ids:
            return []
        return [dict(r) for r in self.q(
            f"SELECT * FROM relationships WHERE src_id IN ({','.join('?' * len(src_ids))})", src_ids)]

    def relationships_to(self, dst_id: str) -> list[dict]:
        return [dict(r) for r in self.q("SELECT * FROM relationships WHERE dst_id=?", (dst_id,))]

    def document_graph(self, document_id: str) -> dict:
        out_edges = self.q(
            "SELECT rel_type, dst_id, dst_label, count(*) n FROM relationships r JOIN chunks c ON c.chunk_id=r.src_id "
            "WHERE c.document_id=? GROUP BY 1,2,3 ORDER BY n DESC", (document_id,))
        in_edges = self.q(
            "SELECT rel_type, c.document_id src_document_id, count(*) n FROM relationships r JOIN chunks c ON c.chunk_id=r.src_id "
            "WHERE r.dst_id=? GROUP BY 1,2 ORDER BY n DESC", (document_id,))
        return {"outgoing": [dict(r) for r in out_edges], "incoming": [dict(r) for r in in_edges]}

    # --------------------------------------------------------------- changes
    def replace_changes(self, old_vid: str, new_vid: str, changes: list[dict]) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM document_changes WHERE old_version_id=? AND new_version_id=?", (old_vid, new_vid))
            c.executemany(
                "INSERT INTO document_changes(old_version_id, new_version_id, change_type, old_section_id, new_section_id, path_text,"
                " old_page, new_page, similarity, diff_text, summary) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(old_vid, new_vid, ch["change_type"], ch.get("old_section_id"), ch.get("new_section_id"), ch["path_text"],
                  ch.get("old_page"), ch.get("new_page"), ch.get("similarity"), ch.get("diff_text"), ch.get("summary")) for ch in changes])

    def changes_between(self, old_vid: str, new_vid: str, path_like: str | None = None) -> list[dict]:
        sql, params = "SELECT * FROM document_changes WHERE old_version_id=? AND new_version_id=?", [old_vid, new_vid]
        if path_like:
            sql += " AND lower(path_text) LIKE ?"; params.append(f"%{path_like.lower()}%")
        sql += " ORDER BY change_id"
        return [dict(r) for r in self.q(sql, params)]

    def has_changes(self, old_vid: str, new_vid: str) -> bool:
        return self.q1("SELECT 1 FROM document_changes WHERE old_version_id=? AND new_version_id=? LIMIT 1", (old_vid, new_vid)) is not None

    # ------------------------------------------------------------- ingestion
    def start_run(self, collector: str) -> str:
        run_id = "run_" + uuid.uuid4().hex[:12]
        self.execute("INSERT INTO ingestion_runs(run_id, collector, started_at, status) VALUES (?,?,?,?)", (run_id, collector, utcnow(), "running"))
        return run_id

    def finish_run(self, run_id: str, status: str, stats: dict) -> None:
        self.execute("UPDATE ingestion_runs SET finished_at=?, status=?, stats=? WHERE run_id=?", (utcnow(), status, _json(stats), run_id))

    def log_item(self, run_id: str, stage: str, status: str, version_id: str | None = None, download_url: str | None = None,
                 error: str | None = None) -> None:
        attempts = 1
        if version_id and status == "failed":
            prev = self.q1("SELECT max(attempts) a FROM ingestion_items WHERE version_id=? AND stage=? AND status='failed'", (version_id, stage))
            attempts = (prev["a"] or 0) + 1
        self.execute("INSERT INTO ingestion_items(run_id, version_id, download_url, stage, status, error, attempts, ts) VALUES (?,?,?,?,?,?,?,?)",
                     (run_id, version_id, download_url, stage, status, (error or "")[:2000] or None, attempts, utcnow()))

    def failure_count(self, version_id: str, stage: str) -> int:
        r = self.q1("SELECT max(attempts) a FROM ingestion_items WHERE version_id=? AND stage=? AND status='failed'", (version_id, stage))
        return int(r["a"] or 0)

    def runs(self, limit: int = 20) -> list[dict]:
        return [dict(r) for r in self.q("SELECT * FROM ingestion_runs ORDER BY started_at DESC LIMIT ?", (limit,))]

    # ------------------------------------------------------------- query log
    def log_query(self, rec: dict) -> None:
        cols = ["query_id", "ts", "mode", "question", "parsed", "filters", "candidates", "context_chunk_ids", "citations",
                "answer", "latency_ms", "model", "embed_model", "tokens", "confidence", "failure"]
        vals = [rec.get(c) for c in cols]
        vals = [(_json(v) if isinstance(v, (dict, list)) else v) for v in vals]
        self.execute(f"INSERT OR REPLACE INTO query_log({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)

    def get_query(self, query_id: str) -> Optional[dict]:
        r = self.q1("SELECT * FROM query_log WHERE query_id=?", (query_id,))
        if not r:
            return None
        d = dict(r)
        for k in ("parsed", "filters", "candidates", "context_chunk_ids", "citations", "answer", "latency_ms", "tokens"):
            try:
                d[k] = json.loads(d[k]) if d.get(k) else None
            except Exception:
                pass
        return d

    def set_feedback(self, query_id: str, feedback: dict) -> None:
        self.execute("UPDATE query_log SET feedback=? WHERE query_id=?", (_json(feedback), query_id))

    def save_citations(self, query_id: str, citations: list[dict]) -> None:
        with self.conn() as c:
            c.executemany(
                "INSERT OR REPLACE INTO citations(citation_id, query_id, chunk_id, version_id, section_id, page, line_ref, quote, label, validated, validation_notes)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(ct["citation_id"], query_id, ct["chunk_id"], ct["version_id"], ct.get("section_id"), ct.get("page"), ct.get("line_ref"),
                  ct.get("quote"), ct.get("label"), 1 if ct.get("validated") else 0, ct.get("validation_notes")) for ct in citations])

    # ------------------------------------------------------------------ eval
    def upsert_eval_question(self, q: dict) -> None:
        self.execute("INSERT OR REPLACE INTO evaluation_questions(qid, category, question, mode, expected, reviewer, notes) VALUES (?,?,?,?,?,?,?)",
                     (q["qid"], q["category"], q["question"], q.get("mode", "research"), _json(q.get("expected", {})), q.get("reviewer"), q.get("notes")))

    def add_eval_result(self, run_id: str, qid: str, strategy: str, metrics: dict, latency_ms: float) -> None:
        self.execute("INSERT INTO evaluation_results(run_id, qid, strategy, metrics, latency_ms, ts) VALUES (?,?,?,?,?,?)",
                     (run_id, qid, strategy, _json(metrics), latency_ms, utcnow()))

    # ----------------------------------------------------------------- stats
    def stats(self) -> dict:
        def n(sql: str) -> int:
            return int(self.q1(sql)[0])
        return {
            "documents": n("SELECT count(*) FROM documents"),
            "versions": n("SELECT count(*) FROM document_versions"),
            "versions_by_state": {r[0]: r[1] for r in self.q("SELECT ingest_state, count(*) FROM document_versions GROUP BY 1")},
            "sections": n("SELECT count(*) FROM sections"),
            "chunks": n("SELECT count(*) FROM chunks"),
            "chunks_by_strategy": {r[0]: r[1] for r in self.q("SELECT strategy, count(*) FROM chunks GROUP BY 1")},
            "embeddings": n("SELECT count(*) FROM embeddings"),
            "relationships": n("SELECT count(*) FROM relationships"),
            "changes": n("SELECT count(*) FROM document_changes"),
            "queries": n("SELECT count(*) FROM query_log"),
            "jurisdictions": {r[0]: r[1] for r in self.q("SELECT jurisdiction, count(*) FROM documents GROUP BY 1")},
        }
