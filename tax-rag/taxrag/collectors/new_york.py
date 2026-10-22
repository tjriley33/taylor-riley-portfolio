"""New York State Department of Taxation and Finance.

Current-year forms live under /pdf/current_forms/it/ (overwritten yearly);
year-stamped copies live under /pdf/<year>/inc/. We prefer year-stamped URLs.
"""
from __future__ import annotations

import re

from ..models import DocumentType
from .base import register
from .states import StateCollector

NY_RE = re.compile(r"/pdf/(?P<year>20\d{2})/inc/(?P<slug>it\d+[a-z]*?)(?P<inst>i)?_(?P=year)(?:_fill_in)?\.pdf$", re.I)
NY_CUR_RE = re.compile(r"/pdf/current_forms/it/(?P<slug>it\d+[a-z]*?)(?P<inst>i)?(?:_fill_in)?\.pdf$", re.I)


@register
class NewYorkCollector(StateCollector):
    name = "new_york"
    authority = "ny_dtf"
    jurisdiction = "NY"
    agency = "New York State Department of Taxation and Finance"
    listing_urls = [
        "https://www.tax.ny.gov/forms/current-forms/it/it201i.htm",
        "https://www.tax.ny.gov/forms/income_cur_forms.htm",
    ]
    allow_patterns = [NY_RE, NY_CUR_RE]

    def classify(self, url, link_text, page_url):
        m = NY_RE.search(url) or NY_CUR_RE.search(url)
        if not m:
            return None
        slug = m.group("slug").upper()           # IT201, IT201ATT, IT225
        form = _dash(slug)                        # IT-201, IT-201-ATT, IT-225
        year = int(m.group("year")) if "year" in m.groupdict() and m.group("year") else None
        inst = bool(m.group("inst"))
        dt = DocumentType.instructions if inst else DocumentType.form
        return self.make(url, page_url, dt, form_number=form, tax_year=year, title=link_text or form)


def _dash(slug: str) -> str:
    m = re.match(r"^(IT)(\d+)([A-Z]+)?$", slug)
    if not m:
        return slug
    out = f"{m.group(1)}-{m.group(2)}"
    if m.group(3):
        out += f"-{m.group(3)}"
    return out
