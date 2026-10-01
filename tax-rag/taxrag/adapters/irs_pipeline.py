"""Adapter: existing IRS-Forms pipeline (DynamoDB `Forms` + S3 `forms123456`) -> DiscoveredDocument.

The Lambda `New_IRS_Forms` remains the federal release detector. This adapter
reads its records (live via boto3, or from a DynamoDB JSON-lines export) and
emits the same DiscoveredDocument objects that collectors emit, so the RAG
pipeline treats the archive as an upstream source of truth without re-crawling.

DynamoDB row shape (Aug-2026 export):
  url, date_released ("2022-06-21 22:11:27"), status ("Draft"|"Final"),
  form_desc ("2025 Form 1040 (PDF)" | "0622 Publ 5649 (PR) (sp) (PDF)" | "2025 Inst 1040 (Schedule C) (PDF)"),
  is_1040 .. is_990 ("X"|""), Is_Form/Inst/Pub ("X"|""), supported (BOOL), owner, file_size

S3 key scheme: Forms/{form name}/{year or "Revision MM.YY"} {Draft|Final}/{filename}.pdf
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Iterator

from ..config import settings
from ..identify import identify_irs_filename, identify_irs_product, parse_revision
from ..models import DiscoveredDocument, DocumentIdentity, DraftOrFinal
from ..collectors.base import TaxAuthorityCollector, register

DESC_RE = re.compile(r"^(?P<rev>\d{4}|[A-Za-z]{3}\s+\d{4})\s+(?P<product>.+?)\s*(?:\(PDF\))?\s*$")
FOREIGN_RE = re.compile(r"\((sp|zh-s|zh-t|ru|ko|vie|ht|pl|pt|fr|ar|tl|km|it|ja|de|bn|ur|gu|fa|pa|so|ne|PR)\)", re.I)

TAX_TYPE_FLAGS = {"is_1040": "1040", "is_1065": "1065", "is_1120": "1120", "is_1120S": "1120S", "is_1041": "1041", "is_990": "990"}


def _unmarshal(item: dict) -> dict:
    """DynamoDB JSON ({'S': ..}) -> plain dict. Accepts already-plain dicts too."""
    out = {}
    for k, v in item.items():
        if isinstance(v, dict) and len(v) == 1:
            (t, val), = v.items()
            if t == "S":
                out[k] = val
            elif t == "N":
                out[k] = float(val)
            elif t == "BOOL":
                out[k] = bool(val)
            elif t == "NULL":
                out[k] = None
            else:
                out[k] = val
        else:
            out[k] = v
    return out


def parse_form_desc(desc: str) -> dict:
    """'2025 Inst 1040 (Schedule C) (PDF)' -> {tax_year: 2025, product: 'Instruction 1040 (Schedule C)'}"""
    m = DESC_RE.match(desc.strip())
    if not m:
        return {}
    tax_year, revision = parse_revision(m.group("rev"))
    product = m.group("product").strip()
    product = re.sub(r"^Inst\b", "Instruction", product)
    product = re.sub(r"^Publ\b", "Publication", product)
    return {"tax_year": tax_year, "revision": revision, "product": product}


def s3_key_for(desc: str, url: str, is_draft: bool) -> str:
    """Replicates main.construct_s3_key from IRS-Forms so we can locate the archived copy."""
    prefix = desc[:4]
    if prefix[:2] in {f"{i:02d}" for i in range(1, 13)} and not prefix.startswith("20"):
        year_or = f"Revision {prefix[:2]}.{prefix[2:]}"
    else:
        year_or = prefix
    d = desc.replace("Inst", "Form")
    form_name = (d[5:-6] if d.endswith(" (PDF)") else d[5:]).strip()
    secondary = f"{year_or} {'Draft' if is_draft else 'Final'}"
    return f"Forms/{form_name}/{secondary}/{url.rsplit('/', 1)[-1]}"


@register
class IRSPipelineAdapter(TaxAuthorityCollector):
    """Reads the existing pipeline's records. `source` = 'export' (JSON lines file) or 'dynamo' (live)."""

    name = "irs_pipeline"
    authority = "irs"
    jurisdiction = "US"
    agency = "IRS"

    def __init__(self, export_path: Path | str | None = None, use_s3: bool = False, supported_only: bool = True,
                 years: list[int] | None = None, **kw):
        super().__init__(include_seeds=False, **kw)
        self.export_path = Path(export_path) if export_path else settings.irs_dynamo_export
        self.use_s3 = use_s3
        self.supported_only = supported_only
        self.years = years

    # ----------------------------------------------------------- records
    def records(self) -> Iterator[dict]:
        if self.export_path and Path(self.export_path).exists():
            with open(self.export_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    yield _unmarshal(d.get("Item", d))
            return
        # live DynamoDB scan
        import boto3  # optional dependency
        table = boto3.resource("dynamodb", region_name=settings.irs_aws_region).Table(settings.irs_dynamo_table)
        resp = table.scan()
        yield from resp.get("Items", [])
        while "LastEvaluatedKey" in resp:
            resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
            yield from resp.get("Items", [])

    def to_discovered(self, rec: dict) -> DiscoveredDocument | None:
        url = rec.get("url") or ""
        desc = rec.get("form_desc") or ""
        if not url.lower().endswith(".pdf") or not desc:
            return None
        if FOREIGN_RE.search(desc):
            return None
        if self.supported_only and rec.get("supported") is False:
            return None
        parsed = parse_form_desc(desc)
        if not parsed:
            return None
        if self.years and parsed["tax_year"] and parsed["tax_year"] not in self.years:
            return None
        fields = identify_irs_product(parsed["product"]) or identify_irs_filename(url.rsplit("/", 1)[-1])
        if not fields.get("document_type"):
            return None
        tax_types = [t for flag, t in TAX_TYPE_FLAGS.items() if str(rec.get(flag, "")).strip().upper() == "X"]
        is_draft = (rec.get("status") == "Draft") or ("--dft" in url)
        ident = DocumentIdentity(
            authority=self.authority, jurisdiction=self.jurisdiction, agency=self.agency,
            document_type=fields["document_type"], form_number=fields.get("form_number"), schedule=fields.get("schedule"),
            publication_number=fields.get("publication_number"), tax_type=tax_types, title=parsed["product"],
        )
        release = (rec.get("date_released") or "")[:10] or None
        disc = DiscoveredDocument(
            identity=ident, source_url="https://www.irs.gov/downloads/irs-dft" if is_draft else "https://www.irs.gov/downloads/irs-pdf",
            download_url=url, tax_year=parsed["tax_year"], revision=parsed["revision"], release_date=release,
            draft_or_final=DraftOrFinal.draft if is_draft else DraftOrFinal.final,
            upstream={"pipeline": "IRS-Forms", "dynamo": rec, "s3_key": s3_key_for(desc, url, is_draft)},
        )
        if self.use_s3:
            disc.local_path = self._fetch_from_s3(disc.upstream["s3_key"])
        return disc

    def _fetch_from_s3(self, key: str) -> str | None:
        try:
            import boto3
            local = settings.data_dir / "s3cache" / key
            local.parent.mkdir(parents=True, exist_ok=True)
            if not local.exists():
                boto3.client("s3").download_file(settings.irs_s3_bucket, key, str(local))
            return str(local)
        except Exception:  # noqa: BLE001  (fall back to download_url)
            return None

    def discover_live(self) -> Iterable[DiscoveredDocument]:
        for rec in self.records():
            d = self.to_discovered(rec)
            if d:
                yield d
