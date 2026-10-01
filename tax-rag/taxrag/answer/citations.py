from __future__ import annotations

import hashlib

from ..models import Citation
from ..store import Store


def build_citation(store: Store, ch: dict, idx: int, quote: str | None = None) -> Citation:
    v = store.get_version(ch["version_id"]) or {}
    d = store.get_document(ch["document_id"]) or {}
    from ..models import DocumentIdentity, DocumentType, ProvenanceClass
    ident = DocumentIdentity(authority=d.get("authority", ""), jurisdiction=d.get("jurisdiction", ""), agency=d.get("agency", ""),
                             document_type=DocumentType(d.get("document_type", "other")), form_number=d.get("form_number"),
                             schedule=d.get("schedule"), publication_number=d.get("publication_number"), title=d.get("title"),
                             provenance_class=ProvenanceClass(d.get("provenance_class", "PUBLIC_AUTHORITY")))
    page = ch["page_start"]
    line_ref = (ch.get("line_refs") or [None])[0]
    cid = "C" + str(idx)
    return Citation(
        citation_id=cid, chunk_id=ch["chunk_id"], version_id=ch["version_id"], document_id=ch["document_id"],
        agency=d.get("agency", ""), jurisdiction=d.get("jurisdiction", ""), document_label=ident.label(),
        tax_year=v.get("tax_year"), revision=v.get("revision"), draft_or_final=v.get("draft_or_final", "final"),
        version_status=v.get("status", "current"), section_path=ch.get("path_text", ""), page=page, line_ref=line_ref,
        source_url=f"{v.get('download_url', '')}#page={page}", local_url=f"/files/{ch['version_id']}.pdf#page={page}",
        quote=quote, provenance_class=d.get("provenance_class", "PUBLIC_AUTHORITY"),
    )


def stable_citation_id(query_id: str, chunk_id: str) -> str:
    return "cit_" + hashlib.sha1(f"{query_id}|{chunk_id}".encode()).hexdigest()[:16]
