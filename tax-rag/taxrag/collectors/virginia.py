"""Virginia Department of Taxation. Forms search returns year-stamped PDF links."""
from __future__ import annotations

import re

from ..models import DocumentType
from .base import register
from .states import StateCollector

FORM_RE = re.compile(r"/individual-income-tax/(?P<year>20\d{2})/(?P<slug>[a-z0-9\-]+)-(?P=year)\.pdf$", re.I)
INST_RE = re.compile(r"/vatax-pdf/(?P<year>20\d{2})-(?P<slug>[a-z0-9\-]+)-instructions\.pdf$", re.I)


@register
class VirginiaCollector(StateCollector):
    name = "virginia"
    authority = "va_tax"
    jurisdiction = "VA"
    agency = "Virginia Department of Taxation"
    listing_urls = [
        "https://www.tax.virginia.gov/forms/search?search=760&year=All&category=All",
        "https://www.tax.virginia.gov/forms/search?search=schedule&year=All&category=All",
    ]
    allow_patterns = [FORM_RE, INST_RE]

    def classify(self, url, link_text, page_url):
        m = INST_RE.search(url)
        if m:
            slug = m.group("slug").lower()
            form, sched = _split(slug)
            dt = DocumentType.schedule_instructions if sched else DocumentType.instructions
            return self.make(url, page_url, dt, form_number=form, schedule=sched, tax_year=int(m.group("year")),
                             title=link_text or f"{slug} instructions")
        m = FORM_RE.search(url)
        if m:
            slug = m.group("slug").lower()
            form, sched = _split(slug)
            dt = DocumentType.schedule if sched else DocumentType.form
            return self.make(url, page_url, dt, form_number=form, schedule=sched, tax_year=int(m.group("year")),
                             title=link_text or slug)
        return None


def _split(slug: str) -> tuple[str | None, str | None]:
    """'760' -> ('760', None); 'schedule-adj' -> ('760','ADJ'); 'sch-cr' -> ('760','CR'); '760py' -> ('760PY', None)."""
    s = slug.replace("schedule-", "sch-")
    if s.startswith("sch-"):
        return "760", s[4:].upper()
    if "-schedule-" in s:
        f, sc = s.split("-schedule-", 1)
        return f.upper(), sc.upper()
    return s.upper(), None
