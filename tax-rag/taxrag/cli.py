"""taxrag command line."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .config import settings

app = typer.Typer(add_completion=False, help="Citation-first federal + state tax RAG")
console = Console()


def _store():
    from .store import Store
    return Store(settings.sqlite_path)


@app.command()
def ingest(collector: str = typer.Argument(..., help="irs | virginia | new_york | wisconsin | arkansas | irs_pipeline | all"),
           live: bool = typer.Option(False, help="also crawl live listing pages (default: seeds only)"),
           limit: Optional[int] = None, no_embed: bool = False, no_diff: bool = False,
           strategies: str = typer.Option(settings.chunk_strategy, help="comma-separated chunk strategies"),
           export: Optional[Path] = typer.Option(None, help="irs_pipeline: DynamoDB JSON-lines export path"),
           years: Optional[str] = typer.Option(None, help="restrict to tax years, e.g. 2024,2025")):
    """Discover, download, parse, chunk, embed and index documents (idempotent)."""
    from .collectors import get_collector
    from .ingest import Ingester
    names = ["irs", "virginia", "new_york", "wisconsin"] if collector == "all" else [collector]
    ing = Ingester(_store(), strategies=strategies.split(","), embed=not no_embed, diff=not no_diff)
    yrs = [int(y) for y in years.split(",")] if years else None
    for name in names:
        kw = {"live": live}
        if name == "irs_pipeline":
            kw.update(export_path=export, years=yrs, live=True)
        elif name == "irs" and yrs:
            kw["years"] = yrs
        col = get_collector(name, **kw)
        console.rule(f"[bold]{name}")
        stats = ing.run_collector(col, limit=limit)
        console.print(json.dumps({k: v for k, v in stats.as_dict().items() if k != "errors"}))
        for e in stats.errors:
            console.print(f"  [red]{e}")


@app.command()
def reindex(strategies: str = settings.chunk_strategy, embeddings_only: bool = False, reparse: bool = False):
    """Re-chunk and/or re-embed every indexed version (--reparse re-extracts text from the stored PDFs)."""
    from .ingest import Ingester
    n = Ingester(_store(), strategies=strategies.split(",")).reindex(strategies=strategies.split(","), embeddings_only=embeddings_only, reparse=reparse)
    console.print(f"reindexed {n} versions")


@app.command()
def ask(question: str, mode: str = "research", jurisdiction: Optional[str] = None, tax_year: Optional[int] = None,
        drafts: Optional[str] = typer.Option(None, help="final | draft"), k: int = settings.context_k, json_out: bool = False,
        no_llm: bool = False):
    """Ask a question. Modes: research | taxdev | source | compare | evidence."""
    from .answer import run_mode
    out = run_mode(_store(), question, mode=mode, jurisdiction=jurisdiction, tax_year=tax_year, draft_filter=drafts, k=k,
                   use_llm=False if no_llm else None)
    if json_out:
        print(json.dumps(out, indent=2, default=str))
        return
    p = out["parsed"]
    console.print(f"[bold]parsed:[/bold] jurisdiction={p['jurisdictions']} year={p['tax_year'] or p['tax_years']} form={p['form']} "
                  f"schedule={p['schedule']} line={p['line']} pub={p['publication']} doctype={p['document_type']} drafts={p['include_drafts']}")
    console.print(f"[bold]filters:[/bold] {out.get('filters_used')}  confidence={out['confidence']}  sufficient={out['sufficient_evidence']}")
    for r in out.get("relaxations", []):
        console.print(f"[yellow]note:[/yellow] {r}")
    if out.get("answer"):
        a = out["answer"]
        console.rule(f"answer ({a.get('generated_by')})")
        console.print(a.get("summary") or "")
        if a.get("note"):
            console.print(f"[dim]{a['note']}[/dim]")
        for c in a.get("claims", []):
            console.print(f"  [{c['label']}] {c['text'][:200]} -> {c['citation_ids']}")
    if out.get("changes"):
        console.rule(f"{len(out['changes'])} stored changes")
        for ch in out["changes"][:15]:
            console.print(f"  {ch['change_type']:18} {ch['path_text'][-80:]}  (p.{ch['old_page']} -> p.{ch['new_page']})")
    console.rule("citations")
    for c in out["citations"]:
        console.print(f"  {c['citation_id']}: {c['rendered']}  {c['source_url']}")
    for cf in out.get("conflicts", []):
        console.print(f"[red]conflict[/red] {cf['type']}: {cf['explanation']}")
    console.rule("evidence")
    for e in out["evidence"]:
        console.print(f"[bold]{e['citation_id']}[/bold] {e['jurisdiction']} {e['tax_year']} {e['draft_or_final']} p.{e['page_start']} via={e['via']} final={e['scores'].get('final')}")
        console.print(f"   {e['path_text']}")
        console.print(f"   [dim]{'; '.join(e['reasons'][:6])}[/dim]")


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False):
    """Run the API + UI."""
    import uvicorn
    uvicorn.run("taxrag.api.app:app", host=host, port=port, reload=reload)


@app.command()
def stats():
    """Store statistics."""
    console.print(json.dumps(_store().stats(), indent=2))


@app.command()
def docs(jurisdiction: Optional[str] = None):
    """List indexed documents and versions."""
    s = _store()
    t = Table("document_id", "jur", "type", "form", "sched", "pub", "versions (year/status/state)")
    for d in s.find_documents(jurisdiction=jurisdiction):
        vs = s.versions_for_document(d["document_id"])
        t.add_row(d["document_id"], d["jurisdiction"], d["document_type"], d["form_number"] or "", d["schedule"] or "", d["publication_number"] or "",
                  ", ".join(f"{v['tax_year'] or v['revision']}/{v['draft_or_final']}/{v['status']}/{v['ingest_state']}" for v in vs))
    console.print(t)


@app.command()
def diff(old_version: str, new_version: str, path: Optional[str] = None):
    """Show stored section-level changes between two versions."""
    s = _store()
    from .diff.sections import diff_versions
    if not s.has_changes(old_version, new_version):
        s.replace_changes(old_version, new_version, diff_versions(s, old_version, new_version))
    for ch in s.changes_between(old_version, new_version, path_like=path):
        console.print(f"[bold]{ch['change_type']}[/bold] {ch['path_text']}  p.{ch['old_page']} -> p.{ch['new_page']}  sim={ch['similarity']}")
        console.print(f"   {ch['summary']}")


@app.command()
def evaluate(strategy: str = settings.chunk_strategy, gold: Optional[Path] = None, use_llm: bool = False, limit: Optional[int] = None,
             report: Optional[Path] = None):
    """Run the evaluation suite."""
    from .eval.harness import run_eval
    res = run_eval(_store(), strategy=strategy, gold_path=gold, use_llm=use_llm, limit=limit)
    console.print(json.dumps(res["summary"], indent=2))
    if report:
        report.write_text(json.dumps(res, indent=2, default=str))
        console.print(f"report written to {report}")


@app.command()
def quarantine(release: Optional[str] = None):
    """List quarantined versions, or release one."""
    s = _store()
    if release:
        from .ingest import Ingester
        Ingester(s).release_quarantine(release)
        console.print(f"released {release}")
        return
    for r in s.q("SELECT version_id, download_url, ingest_state FROM document_versions WHERE quarantined=1"):
        console.print(dict(r))


@app.command()
def debug(query_id: str):
    """Explain why each chunk was retrieved for a logged query."""
    from .observability import debug_view
    print(json.dumps(debug_view(_store(), query_id), indent=2, default=str))


if __name__ == "__main__":
    app()
