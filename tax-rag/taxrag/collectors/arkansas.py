"""Arkansas DFA. The site returns HTTP 403 to non-browser clients, so live discovery
is disabled; documents can be dropped into data/inbox/arkansas/ or seeded with a
browser-fetched copy. See PLUG_IN_LATER.md."""
from __future__ import annotations

from .base import register
from .states import StateCollector


@register
class ArkansasCollector(StateCollector):
    name = "arkansas"
    authority = "ar_dfa"
    jurisdiction = "AR"
    agency = "Arkansas Department of Finance and Administration"
    listing_urls = []  # blocked (403) for scripted clients as of 2026-10-01

    def discover_live(self):
        return []
