"""Domain models shared by collectors, ingestion, retrieval and the API."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ProvenanceClass(str, Enum):
    PUBLIC_AUTHORITY = "PUBLIC_AUTHORITY"
    INTERNAL_TAXDEV = "INTERNAL_TAXDEV"


class DocumentType(str, Enum):
    form = "form"
    instructions = "instructions"
    schedule = "schedule"
    schedule_instructions = "schedule_instructions"
    publication = "publication"
    notice = "notice"
    rev_proc = "rev_proc"
    rev_rul = "rev_rul"
    efile_spec = "efile_spec"
    schema = "schema"
    business_rules = "business_rules"
    faq = "faq"
    guide = "guide"
    worksheet = "worksheet"
    internal = "internal"
    other = "other"


class DraftOrFinal(str, Enum):
    draft = "draft"
    final = "final"
    superseded = "superseded"


TAX_TYPES = ["1040", "1065", "1120", "1120S", "1041", "990"]

# Authority weight used by the reranker and conflict explainer.
AUTHORITY_WEIGHT = {
    DocumentType.form: 1.0,
    DocumentType.instructions: 1.0,
    DocumentType.schedule: 1.0,
    DocumentType.schedule_instructions: 1.0,
    DocumentType.business_rules: 0.95,
    DocumentType.schema: 0.95,
    DocumentType.efile_spec: 0.9,
    DocumentType.rev_proc: 0.9,
    DocumentType.rev_rul: 0.9,
    DocumentType.notice: 0.85,
    DocumentType.publication: 0.8,
    DocumentType.guide: 0.7,
    DocumentType.faq: 0.5,
    DocumentType.worksheet: 0.9,
    DocumentType.internal: 0.0,
    DocumentType.other: 0.4,
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DocumentIdentity(BaseModel):
    """Version-independent identity of a tax product."""

    authority: str                   # irs, va_tax, ny_dtf, wi_dor, ...
    jurisdiction: str                # US, VA, NY, WI, ...
    agency: str                      # "Internal Revenue Service"
    document_type: DocumentType
    form_number: Optional[str] = None       # "1040", "760", "IT-201", "1"
    form_name: Optional[str] = None
    schedule: Optional[str] = None          # "C", "1", "I"
    publication_number: Optional[str] = None
    tax_type: list[str] = Field(default_factory=list)
    title: Optional[str] = None
    provenance_class: ProvenanceClass = ProvenanceClass.PUBLIC_AUTHORITY

    @property
    def document_id(self) -> str:
        key = "|".join([
            self.authority, self.jurisdiction, self.document_type.value,
            (self.form_number or "").upper(), (self.schedule or "").upper(),
            (self.publication_number or "").upper(),
        ])
        return "doc_" + hashlib.sha1(key.encode()).hexdigest()[:16]

    def label(self) -> str:
        parts = []
        if self.document_type in (DocumentType.schedule, DocumentType.schedule_instructions) and self.schedule:
            parts.append(f"Schedule {self.schedule}")
            if self.form_number:
                parts.append(f"(Form {self.form_number})")
            if self.document_type == DocumentType.schedule_instructions:
                parts.insert(0, "Instructions for")
        elif self.document_type == DocumentType.publication and self.publication_number:
            parts.append(f"Publication {self.publication_number}")
        elif self.document_type == DocumentType.instructions and self.form_number:
            parts.append(f"Instructions for Form {self.form_number}")
        elif self.form_number:
            parts.append(f"Form {self.form_number}")
        elif self.title:
            parts.append(self.title)
        return " ".join(parts) or self.document_type.value


class DiscoveredDocument(BaseModel):
    """What a collector knows before downloading."""

    identity: DocumentIdentity
    source_url: str                  # page the link was found on (or the pdf itself)
    download_url: str
    tax_year: Optional[int] = None
    revision: Optional[str] = None         # "12-2023" for continuous-use products
    revision_date: Optional[str] = None
    release_date: Optional[str] = None
    draft_or_final: DraftOrFinal = DraftOrFinal.final
    effective_date: Optional[str] = None
    upstream: dict[str, Any] = Field(default_factory=dict)
    local_path: Optional[str] = None       # pre-downloaded file (e.g. from S3)


class VersionRecord(BaseModel):
    version_id: str
    document_id: str
    tax_year: Optional[int]
    revision: Optional[str]
    revision_date: Optional[str]
    release_date: Optional[str]
    draft_or_final: str
    effective_date: Optional[str]
    source_url: str
    download_url: str
    retrieved_at: str
    file_hash: str
    file_path: str
    page_count: int = 0
    supersedes_version_id: Optional[str] = None
    status: str = "current"
    ingest_state: str = "downloaded"
    title_in_pdf: Optional[str] = None
    pdf_metadata: dict[str, Any] = Field(default_factory=dict)
    upstream: dict[str, Any] = Field(default_factory=dict)


class Block(BaseModel):
    """A layout block on a page after column ordering and paragraph joining."""

    page: int                       # 1-based
    text: str
    kind: str = "para"              # para, heading, line_heading, bullet, tip, caution, note, example, exception, definition, table, worksheet, footer
    level: int = 0                  # heading level when kind in (heading, line_heading)
    font_size: float = 0.0
    bold: bool = False
    italic: bool = False
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    line_ref: Optional[str] = None
    links: list[str] = Field(default_factory=list)


class SectionNode(BaseModel):
    section_id: str
    version_id: str
    parent_section_id: Optional[str]
    level: int
    heading: str
    path: list[str]
    kind: str = "section"
    line_ref: Optional[str] = None
    page_start: int = 0
    page_end: int = 0
    ordinal: int = 0
    text: str = ""
    blocks: list[Block] = Field(default_factory=list)

    @property
    def path_text(self) -> str:
        return " > ".join(self.path)


class ChunkRecord(BaseModel):
    chunk_id: str
    version_id: str
    section_id: Optional[str]
    parent_chunk_id: Optional[str]
    ordinal: int
    text: str
    token_count: int
    page_start: int
    page_end: int
    path_text: str
    kind: str
    line_refs: list[str] = Field(default_factory=list)
    identifiers: str = ""
    strategy: str = "hier_v1"


class Relationship(BaseModel):
    src_type: str
    src_id: str
    rel_type: str
    dst_type: str
    dst_id: Optional[str]
    dst_label: str
    dst_jurisdiction: Optional[str] = None
    confidence: float = 1.0
    evidence_page: Optional[int] = None


class Citation(BaseModel):
    citation_id: str
    chunk_id: str
    version_id: str
    document_id: str
    agency: str
    jurisdiction: str
    document_label: str
    tax_year: Optional[int]
    revision: Optional[str]
    draft_or_final: str
    version_status: str
    section_path: str
    page: int
    line_ref: Optional[str]
    source_url: str
    local_url: str
    quote: Optional[str] = None
    provenance_class: str = "PUBLIC_AUTHORITY"

    def render(self) -> str:
        yr = f"{self.tax_year} " if self.tax_year else (f"Rev. {self.revision} " if self.revision else "")
        status = "" if self.draft_or_final == "final" else f" [{self.draft_or_final.upper()}]"
        leaf = self.section_path.split(" > ")[-1] if self.section_path else ""
        line = f", Line {self.line_ref}" if self.line_ref and f"Line {self.line_ref}" != leaf else ""
        sec = f", {leaf}" if leaf else ""
        prefix = "INTERNAL: " if self.provenance_class != "PUBLIC_AUTHORITY" else ""
        return f"{prefix}{self.agency}, {yr}{self.document_label}{status}{sec}{line}, p. {self.page}."


class Claim(BaseModel):
    text: str
    citation_ids: list[str]
    label: str  # explicit | derived | not_established
    validation: list[str] = Field(default_factory=list)


class RetrievedChunk(BaseModel):
    chunk: dict[str, Any]
    scores: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    via: str = "hybrid"  # hybrid | graph | parent
