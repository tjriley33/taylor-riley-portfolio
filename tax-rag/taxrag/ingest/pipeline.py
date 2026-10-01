"""Idempotent ingestion orchestrator.

discover -> download -> hash/dedupe -> identify -> extract -> normalize -> enrich
-> chunk -> embed -> lexical index -> store -> validate

Each version row carries `ingest_state`; a version only passes through stages it
has not completed. Failures are logged per stage; after MAX_ATTEMPTS the version
is quarantined (excluded from retrieval) until released.
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console

from ..chunk import chunk_sections
from ..collectors import TaxAuthorityCollector
from ..config import settings
from ..diff.sections import diff_versions
from ..embed import embed_passages
from ..graph import extract_relationships
from ..models import DiscoveredDocument, VersionRecord, utcnow
from ..parse import build_sections, extract_pdf
from ..store import Store

console = Console()
MAX_ATTEMPTS = 3
STAGES = ["downloaded", "parsed", "chunked", "embedded", "indexed"]


@dataclass
class RunStats:
    discovered: int = 0
    downloaded: int = 0
    unchanged: int = 0
    new_versions: int = 0
    superseded: int = 0
    parsed: int = 0
    chunked: int = 0
    embedded: int = 0
    diffed: int = 0
    failed: int = 0
    quarantined: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


class Ingester:
    def __init__(self, store: Store, strategies: list[str] | None = None, embed: bool = True, diff: bool = True):
        self.store = store
        self.strategies = strategies or [settings.chunk_strategy]
        self.embed = embed
        self.diff = diff

    # ------------------------------------------------------------- driver
    def run_collector(self, collector: TaxAuthorityCollector, limit: int | None = None, only_urls: set[str] | None = None) -> RunStats:
        run_id = self.store.start_run(collector.name)
        stats = RunStats()
        try:
            for disc in collector.discover_documents():
                if only_urls and disc.download_url not in only_urls:
                    continue
                stats.discovered += 1
                if limit and stats.discovered > limit:
                    break
                try:
                    self.ingest_discovered(collector, disc, run_id, stats)
                except Exception as e:  # noqa: BLE001
                    stats.failed += 1
                    msg = f"{disc.download_url}: {e}"
                    stats.errors.append(msg)
                    console.print(f"[red]FAIL[/red] {msg}")
                    self.store.log_item(run_id, "ingest", "failed", download_url=disc.download_url, error=traceback.format_exc())
            self.store.finish_run(run_id, "ok" if not stats.failed else "partial", stats.as_dict())
        except Exception as e:  # noqa: BLE001
            self.store.finish_run(run_id, "failed", {**stats.as_dict(), "fatal": str(e)})
            raise
        return stats

    # ------------------------------------------------------- per document
    def ingest_discovered(self, collector: TaxAuthorityCollector, disc: DiscoveredDocument, run_id: str, stats: RunStats) -> str | None:
        disc = collector.normalize_document(disc)
        # 1. download + hash
        path, sha = collector.fetch_document(disc)
        stats.downloaded += 1
        existing = self.store.get_version(sha)
        if existing:
            if existing["quarantined"]:
                console.print(f"[yellow]quarantined[/yellow] {disc.download_url}")
                return sha
            stats.unchanged += 1
            self.store.log_item(run_id, "download", "skipped", version_id=sha, download_url=disc.download_url)
            self.advance(sha, run_id, stats)  # finish any incomplete stages
            return sha

        # 2. identify + enrich from the PDF itself
        ex = extract_pdf(path)
        disc = collector.extract_metadata(disc, ex.metadata, ex.first_pages_text)
        document_id = self.store.upsert_document(disc.identity)

        # 3. supersession: same URL previously current with a different hash
        prev = self.store.version_by_url_current(disc.download_url)
        version = VersionRecord(
            version_id=sha, document_id=document_id, tax_year=disc.tax_year, revision=disc.revision,
            revision_date=disc.revision_date, release_date=disc.release_date, draft_or_final=disc.draft_or_final.value,
            effective_date=disc.effective_date, source_url=disc.source_url, download_url=disc.download_url,
            retrieved_at=utcnow(), file_hash=sha, file_path=str(path), page_count=ex.page_count,
            title_in_pdf=ex.metadata.get("title"), pdf_metadata=ex.metadata, upstream=disc.upstream,
        )
        self.store.insert_version(version)
        stats.new_versions += 1
        self.store.log_item(run_id, "download", "ok", version_id=sha, download_url=disc.download_url)
        if prev and prev["version_id"] != sha:
            self.store.supersede(prev["version_id"], sha)
            stats.superseded += 1
            console.print(f"[cyan]superseded[/cyan] {disc.download_url} {prev['version_id'][:8]} -> {sha[:8]}")
        self.store.recompute_current_status(document_id)
        if ex.needs_ocr_pages:
            frac = len(ex.needs_ocr_pages) / max(1, ex.page_count)
            self.store.update_version(sha, needs_ocr=1 if frac > 0.4 else 0)
        console.print(f"[green]new[/green] {disc.identity.label()} {disc.tax_year or disc.revision or ''} {disc.draft_or_final.value} ({ex.page_count}p) {sha[:8]}")
        self.advance(sha, run_id, stats, extraction=ex)
        return sha

    # ------------------------------------------------------------- stages
    def advance(self, version_id: str, run_id: str, stats: RunStats, extraction=None) -> None:
        v = self.store.get_version(version_id)
        if not v or v["quarantined"]:
            return
        doc = self.store.get_document(v["document_id"])
        state = v["ingest_state"]
        try:
            if state == "downloaded":
                ex = extraction or extract_pdf(v["file_path"])
                sections = build_sections(ex, version_id, doc.get("title") or v.get("title_in_pdf") or "")
                self.store.replace_sections(version_id, sections)
                self.store.update_version(version_id, ingest_state="parsed")
                self.store.log_item(run_id, "parse", "ok", version_id=version_id)
                stats.parsed += 1
                state = "parsed"
                self._sections_cache = (version_id, sections)
            if state == "parsed":
                sections = self._load_sections(version_id)
                v = self.store.get_version(version_id)
                for strategy in self.strategies:
                    chunks = chunk_sections(strategy, sections, version_id, doc)
                    self.store.replace_chunks(version_id, strategy, chunks, v, doc)
                    if strategy == self.strategies[0]:
                        rels = extract_relationships(self.store, chunks, doc, v)
                        self.store.replace_relationships(version_id, rels)
                self.store.update_version(version_id, ingest_state="chunked")
                self.store.log_item(run_id, "chunk", "ok", version_id=version_id)
                stats.chunked += 1
                state = "chunked"
            if state == "chunked":
                if self.embed:
                    for strategy in self.strategies:
                        missing = self.store.missing_embeddings(version_id, strategy, settings.embed_model)
                        for i in range(0, len(missing), 256):
                            batch = missing[i:i + 256]
                            vecs = embed_passages([c["text"] for c in batch])
                            self.store.replace_embeddings([(c["chunk_id"], vecs[j]) for j, c in enumerate(batch)], settings.embed_model, strategy)
                    self.store.update_version(version_id, ingest_state="embedded")
                    self.store.log_item(run_id, "embed", "ok", version_id=version_id)
                    stats.embedded += 1
                    state = "embedded"
            if state == "embedded":
                self.validate(version_id)
                self.store.update_version(version_id, ingest_state="indexed")
                self.store.log_item(run_id, "validate", "ok", version_id=version_id)
                state = "indexed"
            if state == "indexed" and self.diff:
                self.diff_against_neighbors(version_id, stats)
        except Exception as e:  # noqa: BLE001
            stage = {"downloaded": "parse", "parsed": "chunk", "chunked": "embed", "embedded": "validate"}.get(state, state)
            self.store.log_item(run_id, stage, "failed", version_id=version_id, error=traceback.format_exc())
            attempts = self.store.failure_count(version_id, stage)
            stats.failed += 1
            if attempts >= MAX_ATTEMPTS:
                self.store.update_version(version_id, quarantined=1, ingest_state="quarantined")
                stats.quarantined += 1
                console.print(f"[red]QUARANTINED[/red] {version_id[:8]} at {stage}: {e}")
            else:
                console.print(f"[red]fail[/red] {version_id[:8]} at {stage} (attempt {attempts}): {e}")

    _sections_cache: tuple[str, list] | None = None

    def _load_sections(self, version_id: str):
        if self._sections_cache and self._sections_cache[0] == version_id:
            return self._sections_cache[1]
        from ..models import SectionNode, Block
        import json
        rows = self.store.sections_for_version(version_id)
        secs = []
        for r in rows:
            s = SectionNode(section_id=r["section_id"], version_id=r["version_id"], parent_section_id=r["parent_section_id"],
                            level=r["level"], heading=r["heading"], path=json.loads(r["path"]), kind=r["kind"], line_ref=r["line_ref"],
                            page_start=r["page_start"], page_end=r["page_end"], ordinal=r["ordinal"], text=r["text"])
            # rebuild blocks approximately (one per paragraph) so baseline strategies can run from the store
            s.blocks = [Block(page=r["page_start"], text=t, kind="para") for t in r["text"].split("\n") if t.strip()]
            secs.append(s)
        return secs

    # ---------------------------------------------------------- validate
    def validate(self, version_id: str) -> None:
        v = self.store.get_version(version_id)
        n_sec = self.store.q1("SELECT count(*) n FROM sections WHERE version_id=?", (version_id,))["n"]
        n_chk = self.store.q1("SELECT count(*) n FROM chunks WHERE version_id=? AND strategy=?", (version_id, self.strategies[0]))["n"]
        n_fts = self.store.q1("SELECT count(*) n FROM chunk_fts f JOIN chunks c ON c.chunk_id=f.chunk_id WHERE c.version_id=? AND c.strategy=?", (version_id, self.strategies[0]))["n"]
        n_emb = self.store.q1("SELECT count(*) n FROM embeddings e JOIN chunks c ON c.chunk_id=e.chunk_id WHERE c.version_id=? AND c.strategy=? AND e.model=?",
                              (version_id, self.strategies[0], settings.embed_model))["n"]
        problems = []
        if v["page_count"] == 0:
            problems.append("no pages")
        if n_sec == 0:
            problems.append("no sections")
        if n_chk == 0:
            problems.append("no chunks")
        if n_fts != n_chk:
            problems.append(f"fts rows {n_fts} != chunks {n_chk}")
        if self.embed and n_emb != n_chk:
            problems.append(f"embeddings {n_emb} != chunks {n_chk}")
        if problems:
            raise RuntimeError("validation failed: " + "; ".join(problems))

    # -------------------------------------------------------------- diff
    def diff_against_neighbors(self, version_id: str, stats: RunStats) -> None:
        """Compute section diffs vs. the previous version of the same product (prior year final or superseded hash)."""
        v = self.store.get_version(version_id)
        versions = self.store.versions_for_document(v["document_id"])
        candidates = []
        if v.get("supersedes_version_id"):
            candidates.append(v["supersedes_version_id"])
        # previous tax year, final, current
        if v["tax_year"]:
            prev_years = sorted({x["tax_year"] for x in versions if x["tax_year"] and x["tax_year"] < v["tax_year"]}, reverse=True)
            if prev_years:
                for x in versions:
                    if x["tax_year"] == prev_years[0] and x["draft_or_final"] == "final" and x["status"] == "current":
                        candidates.append(x["version_id"])
            # draft vs. same-year final (draft for year Y compared with final of year Y-1 handled above; also same-year final)
            if v["draft_or_final"] == "draft":
                for x in versions:
                    if x["tax_year"] == v["tax_year"] and x["draft_or_final"] == "final" and x["status"] == "current":
                        candidates.append(x["version_id"])
        pairs = [(old, version_id) for old in dict.fromkeys(candidates)]
        # also diff newer versions that were indexed before this (older) one arrived
        if v["tax_year"]:
            for x in versions:
                if x["tax_year"] and x["tax_year"] > v["tax_year"] and x["status"] == "current" and v["draft_or_final"] == "final" \
                        and (x["tax_year"] == v["tax_year"] + 1):
                    pairs.append((version_id, x["version_id"]))
        for old, new in dict.fromkeys(pairs):
            if old == new or self.store.has_changes(old, new):
                continue
            ov, nv = self.store.get_version(old), self.store.get_version(new)
            if not ov or not nv or ov["ingest_state"] not in ("indexed", "embedded", "chunked", "parsed") \
                    or nv["ingest_state"] not in ("indexed", "embedded", "chunked", "parsed"):
                continue
            changes = diff_versions(self.store, old, new)
            self.store.replace_changes(old, new, changes)
            stats.diffed += 1
            console.print(f"[magenta]diff[/magenta] {ov['tax_year']} {ov['draft_or_final']} -> {nv['tax_year']} {nv['draft_or_final']}: {len(changes)} changes")

    # ----------------------------------------------------------- reindex
    def reindex(self, strategies: list[str] | None = None, embeddings_only: bool = False, reparse: bool = False) -> int:
        """Re-chunk/re-embed every indexed version (e.g. after a chunker or model change). reparse=True re-extracts from the PDF."""
        strategies = strategies or self.strategies
        self.strategies = strategies
        run_id = self.store.start_run("reindex")
        stats = RunStats()
        n = 0
        for r in self.store.q("SELECT version_id FROM document_versions WHERE quarantined=0"):
            vid = r["version_id"]
            self.store.update_version(vid, ingest_state="downloaded" if reparse else ("chunked" if embeddings_only else "parsed"))
            self.advance(vid, run_id, stats)
            n += 1
        self.store.finish_run(run_id, "ok", stats.as_dict())
        return n

    def release_quarantine(self, version_id: str) -> None:
        self.store.update_version(version_id, quarantined=0, ingest_state="downloaded")
