"""IRS collector: current, prior-year and draft listing pages on irs.gov + curated seeds."""
from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..identify import identify_irs_filename, identify_irs_product, parse_revision, tax_types_for
from ..models import DiscoveredDocument, DocumentIdentity, DocumentType, DraftOrFinal
from .base import TaxAuthorityCollector, register
from . import http

LISTING_PAGES = {
    "current": "https://www.irs.gov/forms-instructions-and-publications?find={find}&items_per_page=200&page={page}",
    "prior": "https://www.irs.gov/prior-year-forms-and-instructions?find={find}&items_per_page=200&page={page}",
    "draft": "https://www.irs.gov/draft-tax-forms?find={find}&items_per_page=200&page={page}",
}

# Non-English variants are tracked but not ingested by default.
FOREIGN_RE = re.compile(r"\((sp|zh-s|zh-t|ru|ko|vie|ht|pl|pt|fr|ar|tl|km|it|ja|de|bn|ur|gu|fa|pa|so|ne)\)", re.I)


@register
class IRSCollector(TaxAuthorityCollector):
    name = "irs"
    authority = "irs"
    jurisdiction = "US"
    agency = "IRS"

    def __init__(self, finds: list[str] | None = None, listings: list[str] | None = None, max_pages: int = 2,
                 years: list[int] | None = None, **kw):
        super().__init__(**kw)
        self.finds = finds or ["1040", "1065", "1120", "1041", "990"]
        self.listings = listings or ["current", "draft"]
        self.max_pages = max_pages
        self.years = years

    def discover_live(self) -> Iterable[DiscoveredDocument]:
        for listing in self.listings:
            for find in self.finds:
                for page in range(self.max_pages):
                    url = LISTING_PAGES[listing].format(find=find, page=page)
                    html = http.get_text(url)
                    rows = list(self._parse_listing(html, url, listing))
                    if not rows:
                        break
                    yield from rows

    def _parse_listing(self, html: str, page_url: str, listing: str) -> Iterable[DiscoveredDocument]:
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")
        if not table:
            return
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue
            a = tds[0].find("a", href=True)
            if not a or not a["href"].lower().endswith(".pdf"):
                continue
            product = a.get_text(" ", strip=True)
            title = tds[1].get_text(" ", strip=True)
            revision = tds[2].get_text(" ", strip=True)
            posted = tds[3].get_text(" ", strip=True) if len(tds) > 3 else None
            if FOREIGN_RE.search(product):
                continue
            pdf_url = urljoin(page_url, a["href"])
            ident_fields = identify_irs_product(product, title)
            fn_fields = identify_irs_filename(pdf_url.rsplit("/", 1)[-1])
            if not ident_fields:
                ident_fields = fn_fields
            if not ident_fields.get("document_type"):
                continue
            tax_year, rev = parse_revision(revision)
            if self.years and tax_year and tax_year not in self.years:
                continue
            draft = DraftOrFinal.draft if (listing == "draft" or "--dft" in pdf_url) else DraftOrFinal.final
            form_number = ident_fields.get("form_number")
            ident = DocumentIdentity(
                authority=self.authority, jurisdiction=self.jurisdiction, agency=self.agency,
                document_type=ident_fields["document_type"], form_number=form_number,
                schedule=ident_fields.get("schedule"), publication_number=ident_fields.get("publication_number"),
                tax_type=tax_types_for(form_number, ident_fields.get("schedule"), title), title=title,
            )
            yield DiscoveredDocument(
                identity=ident, source_url=page_url, download_url=pdf_url, tax_year=tax_year, revision=rev,
                release_date=_iso(posted), draft_or_final=draft,
                upstream={"listing": listing, "product": product, "revision_text": revision},
            )


def _iso(mdy: str | None) -> str | None:
    if not mdy:
        return None
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", mdy.strip())
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else None
