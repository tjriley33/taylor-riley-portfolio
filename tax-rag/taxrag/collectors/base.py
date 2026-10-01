"""Common collector interface.

Every jurisdiction implements the same four operations so the ingestion
pipeline never needs to know about site-specific quirks.
"""
from __future__ import annotations

import abc
from pathlib import Path
from typing import Iterable, Iterator

import yaml

from ..config import settings
from ..identify import detect_draft_in_text, guess_tax_year_from_text
from ..models import DiscoveredDocument, DocumentIdentity, DocumentType, DraftOrFinal, ProvenanceClass
from . import http

SEEDS_DIR = Path(__file__).with_name("seeds")


class TaxAuthorityCollector(abc.ABC):
    """Interface: discover_documents() -> fetch_document() -> extract_metadata() -> normalize_document()."""

    name: str = "base"
    authority: str = "unknown"
    jurisdiction: str = "US"
    agency: str = "Unknown Agency"
    provenance_class: ProvenanceClass = ProvenanceClass.PUBLIC_AUTHORITY

    def __init__(self, include_seeds: bool = True, live: bool = True):
        self.include_seeds = include_seeds
        self.live = live

    # ------------------------------------------------------------ discover
    def discover_documents(self) -> Iterator[DiscoveredDocument]:
        seen: set[str] = set()
        if self.include_seeds:
            for d in self.seed_documents():
                if d.download_url not in seen:
                    seen.add(d.download_url)
                    yield d
        if self.live:
            try:
                for d in self.discover_live():
                    if d.download_url not in seen:
                        seen.add(d.download_url)
                        yield d
            except Exception as e:  # noqa: BLE001
                # Live discovery is best-effort; seeds still flow.
                print(f"[{self.name}] live discovery failed: {e}")

    def discover_live(self) -> Iterable[DiscoveredDocument]:
        return []

    def seed_documents(self) -> Iterator[DiscoveredDocument]:
        path = SEEDS_DIR / f"{self.name}.yaml"
        if not path.exists():
            return
        data = yaml.safe_load(path.read_text()) or {}
        for entry in data.get("documents", []):
            yield self.seed_to_discovered(entry)

    def seed_to_discovered(self, e: dict) -> DiscoveredDocument:
        ident = DocumentIdentity(
            authority=self.authority, jurisdiction=self.jurisdiction, agency=self.agency,
            document_type=DocumentType(e["document_type"]),
            form_number=e.get("form_number"), form_name=e.get("form_name"), schedule=e.get("schedule"),
            publication_number=e.get("publication_number"), tax_type=e.get("tax_type", []), title=e.get("title"),
            provenance_class=self.provenance_class,
        )
        return DiscoveredDocument(
            identity=ident, source_url=e.get("source_url", e["url"]), download_url=e["url"],
            tax_year=e.get("tax_year"), revision=e.get("revision"), release_date=e.get("release_date"),
            draft_or_final=DraftOrFinal(e.get("draft_or_final", "final")), upstream={"seed": True},
        )

    # --------------------------------------------------------------- fetch
    def fetch_document(self, disc: DiscoveredDocument) -> tuple[Path, str]:
        """Return (local path, sha256). Honors a pre-fetched local_path (e.g. from S3)."""
        if disc.local_path and Path(disc.local_path).exists():
            p = Path(disc.local_path)
            return p, http.hash_file(p)
        return http.download(disc.download_url, settings.raw_dir)

    # ------------------------------------------------------------ metadata
    def extract_metadata(self, disc: DiscoveredDocument, pdf_meta: dict, first_pages_text: str) -> DiscoveredDocument:
        """Fill gaps from the PDF itself. Never override explicit seed/listing metadata."""
        if disc.tax_year is None and disc.revision is None:
            y = guess_tax_year_from_text(first_pages_text)
            if y:
                disc.tax_year = y
        if disc.draft_or_final == DraftOrFinal.final and detect_draft_in_text(first_pages_text[:6000]):
            disc.draft_or_final = DraftOrFinal.draft
        if not disc.identity.title and pdf_meta.get("title"):
            disc.identity.title = pdf_meta["title"].strip()
        return disc

    # ----------------------------------------------------------- normalize
    def normalize_document(self, disc: DiscoveredDocument) -> DiscoveredDocument:
        if disc.identity.form_number:
            disc.identity.form_number = disc.identity.form_number.upper().replace("FORM ", "").strip()
        if disc.identity.schedule:
            disc.identity.schedule = disc.identity.schedule.upper().strip()
        return disc


COLLECTORS: dict[str, type[TaxAuthorityCollector]] = {}


def register(cls: type[TaxAuthorityCollector]) -> type[TaxAuthorityCollector]:
    COLLECTORS[cls.name] = cls
    return cls


def get_collector(name: str, **kw) -> TaxAuthorityCollector:
    # import side-effect registration
    from . import irs, virginia, new_york, wisconsin, arkansas  # noqa: F401
    if name not in COLLECTORS:
        raise KeyError(f"unknown collector {name}; known: {sorted(COLLECTORS)}")
    return COLLECTORS[name](**kw)
