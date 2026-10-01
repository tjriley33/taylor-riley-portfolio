"""FastAPI surface. Structured JSON everywhere; the analyst UI is served at /."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from ..answer import run_mode
from ..config import settings
from ..retrieve import parse_query, retrieve
from ..store import Store

app = FastAPI(title="TaxRAG", version="0.1.0", description="Citation-first federal + state tax research API")
_store: Store | None = None


def store() -> Store:
    global _store
    if _store is None:
        _store = Store(settings.sqlite_path)
    return _store


class SearchRequest(BaseModel):
    query: str
    jurisdiction: Optional[str] = None
    tax_year: Optional[int] = None
    tax_type: Optional[str] = None
    document_types: Optional[list[str]] = None
    draft_filter: Optional[str] = Field(default=None, description="final | draft | all")
    k: int = 10
    strategy: Optional[str] = None


class AskRequest(SearchRequest):
    mode: str = "research"
    include_internal: bool = False
    use_llm: Optional[bool] = None


class CompareRequest(BaseModel):
    query: str
    jurisdiction: Optional[str] = None
    years: Optional[list[int]] = None
    tax_type: Optional[str] = None
    document_types: Optional[list[str]] = None
    include_drafts: bool = True
    k: int = 8


class FeedbackRequest(BaseModel):
    query_id: str
    rating: int
    comment: Optional[str] = None
    bad_citation_ids: Optional[list[str]] = None


@app.get("/", response_class=HTMLResponse)
def ui() -> str:
    return (Path(__file__).parent.parent / "ui" / "index.html").read_text()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "db": str(settings.sqlite_path), **store().stats()}


@app.post("/search")
def search(req: SearchRequest) -> dict:
    out = run_mode(store(), req.query, mode="source", jurisdiction=req.jurisdiction, tax_year=req.tax_year, tax_type=req.tax_type,
                   document_types=req.document_types, draft_filter=req.draft_filter, k=req.k, strategy=req.strategy)
    return out


@app.post("/ask")
def ask(req: AskRequest) -> dict:
    try:
        return run_mode(store(), req.query, mode=req.mode, jurisdiction=req.jurisdiction, tax_year=req.tax_year, tax_type=req.tax_type,
                        document_types=req.document_types, draft_filter=req.draft_filter, k=req.k, strategy=req.strategy,
                        include_internal=req.include_internal, use_llm=req.use_llm)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/compare")
def compare(req: CompareRequest) -> dict:
    q = req.query
    if req.years and len(req.years) == 2 and not any(str(y) in q for y in req.years):
        q = f"{q} between {req.years[0]} and {req.years[1]}"
    return run_mode(store(), q, mode="compare", jurisdiction=req.jurisdiction, tax_type=req.tax_type, document_types=req.document_types,
                    draft_filter=None if req.include_drafts else "final", k=req.k)


@app.get("/documents")
def documents(jurisdiction: Optional[str] = None, document_type: Optional[str] = None, form_number: Optional[str] = None) -> list[dict]:
    s = store()
    docs = s.find_documents(jurisdiction=jurisdiction, document_type=document_type, form_number=form_number)
    for d in docs:
        d["versions"] = s.available_years(d["document_id"])
    return docs


@app.get("/documents/{document_id}")
def document(document_id: str) -> dict:
    d = store().get_document(document_id)
    if not d:
        raise HTTPException(404, "document not found")
    d["versions"] = store().versions_for_document(document_id)
    d["graph"] = store().document_graph(document_id)
    return d


@app.get("/documents/{document_id}/versions")
def document_versions(document_id: str) -> list[dict]:
    return store().versions_for_document(document_id)


@app.get("/versions/{version_id}")
def version(version_id: str) -> dict:
    v = store().get_version(version_id)
    if not v:
        raise HTTPException(404, "version not found")
    v["document"] = store().get_document(v["document_id"])
    return v


@app.get("/versions/{version_id}/sections")
def version_sections(version_id: str, max_level: int = 3) -> list[dict]:
    return [{k: v for k, v in s.items() if k != "text"} | {"chars": len(s["text"])} for s in store().sections_for_version(version_id) if s["level"] <= max_level]


@app.get("/sections/{section_id}")
def section(section_id: str) -> dict:
    s = store().get_section(section_id)
    if not s:
        raise HTTPException(404, "section not found")
    s["chunks"] = store().chunks_for_section(section_id, settings.chunk_strategy)
    return s


@app.get("/chunks/{chunk_id}")
def chunk(chunk_id: str) -> dict:
    c = store().get_chunk(chunk_id)
    if not c:
        raise HTTPException(404, "chunk not found")
    c["version"] = store().get_version(c["version_id"])
    c["relationships"] = store().relationships_from([chunk_id])
    return c


@app.get("/sources/{citation}")
def source(citation: str) -> dict:
    """Resolve a citation id (cit_...) or chunk id (chk_...) to the passage + original document link."""
    s = store()
    chunk_id = citation
    if citation.startswith("cit_"):
        r = s.q1("SELECT * FROM citations WHERE citation_id=?", (citation,))
        if not r:
            raise HTTPException(404, "citation not found")
        chunk_id = r["chunk_id"]
    c = s.get_chunk(chunk_id)
    if not c:
        raise HTTPException(404, "chunk not found")
    v = s.get_version(c["version_id"])
    d = s.get_document(c["document_id"])
    return {"chunk": c, "version": v, "document": d, "local_url": f"/files/{c['version_id']}.pdf#page={c['page_start']}",
            "source_url": f"{v['download_url']}#page={c['page_start']}", "section": s.get_section(c["section_id"]) if c.get("section_id") else None}


@app.get("/files/{version_id}.pdf")
def file(version_id: str):
    v = store().get_version(version_id)
    if not v or not Path(v["file_path"]).exists():
        raise HTTPException(404, "file not found")
    return FileResponse(v["file_path"], media_type="application/pdf", filename=Path(v["download_url"]).name,
                        headers={"Content-Disposition": "inline"})


@app.get("/changes")
def changes(old: str, new: str, path: Optional[str] = None) -> list[dict]:
    return store().changes_between(old, new, path_like=path)


@app.get("/graph/{document_id}")
def graph(document_id: str) -> dict:
    return store().document_graph(document_id)


@app.get("/queries/{query_id}")
def query_debug(query_id: str) -> dict:
    q = store().get_query(query_id)
    if not q:
        raise HTTPException(404, "query not found")
    return q


@app.get("/queries")
def recent_queries(limit: int = 50) -> list[dict]:
    return [dict(r) for r in store().q("SELECT query_id, ts, mode, question, confidence, failure, model FROM query_log ORDER BY ts DESC LIMIT ?", (limit,))]


@app.post("/feedback")
def feedback(req: FeedbackRequest) -> dict:
    store().set_feedback(req.query_id, req.model_dump())
    return {"ok": True}


@app.get("/meta/filters")
def meta_filters() -> dict:
    s = store()
    return {
        "jurisdictions": [r[0] for r in s.q("SELECT DISTINCT jurisdiction FROM documents ORDER BY 1")],
        "tax_years": [r[0] for r in s.q("SELECT DISTINCT tax_year FROM document_versions WHERE tax_year IS NOT NULL ORDER BY 1 DESC")],
        "tax_types": ["1040", "1065", "1120", "1120S", "1041", "990"],
        "document_types": [r[0] for r in s.q("SELECT DISTINCT document_type FROM documents ORDER BY 1")],
        "forms": [dict(r) for r in s.q("SELECT jurisdiction, form_number, count(*) n FROM documents WHERE form_number IS NOT NULL GROUP BY 1,2 ORDER BY 1,2")],
        "current_tax_year": settings.current_tax_year,
        "llm_available": __import__("taxrag.answer.llm", fromlist=["available"]).available(),
    }


@app.get("/admin/stats")
def admin_stats() -> dict:
    return store().stats()


@app.get("/admin/runs")
def admin_runs(limit: int = 20) -> list[dict]:
    return store().runs(limit)


@app.post("/admin/reindex")
def admin_reindex(strategies: Optional[list[str]] = None, embeddings_only: bool = False) -> dict:
    from ..ingest import Ingester
    n = Ingester(store(), strategies=strategies).reindex(strategies=strategies, embeddings_only=embeddings_only)
    return {"reindexed_versions": n}


@app.post("/admin/ingest/{collector}")
def admin_ingest(collector: str, limit: Optional[int] = None, live: bool = False) -> dict:
    from ..collectors import get_collector
    from ..ingest import Ingester
    col = get_collector(collector, live=live)
    stats = Ingester(store()).run_collector(col, limit=limit)
    return stats.as_dict()
