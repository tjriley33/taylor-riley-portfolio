"""Wisconsin Department of Revenue. Year-stamped URLs: /TaxForms<year>/<year>-<Product>[f|-Inst].pdf"""
from __future__ import annotations

import re

from ..models import DocumentType
from .base import register
from .states import StateCollector

WI_RE = re.compile(r"/TaxForms(?P<year>20\d{2})/(?P=year)-(?P<prod>[A-Za-z0-9]+?)(?P<kind>f|-Inst|-inst|-Instr)\.pdf$")


@register
class WisconsinCollector(StateCollector):
    name = "wisconsin"
    authority = "wi_dor"
    jurisdiction = "WI"
    agency = "Wisconsin Department of Revenue"
    listing_urls = ["https://www.revenue.wi.gov/Pages/Form/2025Individual.aspx"]
    allow_patterns = [WI_RE]

    def classify(self, url, link_text, page_url):
        m = WI_RE.search(url)
        if not m:
            return None
        prod = m.group("prod")
        year = int(m.group("year"))
        inst = m.group("kind").lower() != "f"
        if prod.lower().startswith("schedule"):
            sched = prod[len("Schedule"):].upper()
            dt = DocumentType.schedule_instructions if inst else DocumentType.schedule
            return self.make(url, page_url, dt, form_number="1", schedule=sched, tax_year=year, title=link_text or f"Schedule {sched}")
        if prod.lower().startswith("form"):
            form = prod[4:].upper()
            dt = DocumentType.instructions if inst else DocumentType.form
            return self.make(url, page_url, dt, form_number=form, tax_year=year, title=link_text or f"Form {form}")
        return None
