"""Shared helpers for state collectors."""
from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import DiscoveredDocument, DocumentIdentity, DocumentType, DraftOrFinal
from .base import TaxAuthorityCollector

YEAR_RE = re.compile(r"(20[12]\d)")


class StateCollector(TaxAuthorityCollector):
    """Base for state DORs: a listing page with PDF links + per-state filename grammar."""

    listing_urls: list[str] = []
    allow_patterns: list[re.Pattern] = []

    def discover_live(self) -> Iterable[DiscoveredDocument]:
        from . import http
        for page_url in self.listing_urls:
            html = http.get_text(page_url)
            soup = BeautifulSoup(html, "lxml")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if ".pdf" not in href.lower():
                    continue
                url = urljoin(page_url, href)
                if self.allow_patterns and not any(p.search(url) for p in self.allow_patterns):
                    continue
                text = a.get_text(" ", strip=True)
                disc = self.classify(url, text, page_url)
                if disc:
                    yield disc

    def classify(self, url: str, link_text: str, page_url: str) -> DiscoveredDocument | None:  # pragma: no cover - overridden
        return None

    def make(self, url: str, page_url: str, document_type: DocumentType, form_number: str | None = None,
             schedule: str | None = None, title: str | None = None, tax_year: int | None = None,
             tax_type: list[str] | None = None, draft: bool = False, publication_number: str | None = None) -> DiscoveredDocument:
        ident = DocumentIdentity(
            authority=self.authority, jurisdiction=self.jurisdiction, agency=self.agency, document_type=document_type,
            form_number=form_number, schedule=schedule, publication_number=publication_number,
            tax_type=tax_type or ["1040"], title=title,
        )
        return DiscoveredDocument(identity=ident, source_url=page_url, download_url=url, tax_year=tax_year,
                                  draft_or_final=DraftOrFinal.draft if draft else DraftOrFinal.final,
                                  upstream={"listing": page_url})
