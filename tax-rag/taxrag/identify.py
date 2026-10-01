"""Best-effort identification of a tax document from filename, listing title and PDF text.

Collectors pass what the listing page knows; this module fills gaps and
normalizes. It is deliberately conservative: when unsure it returns None and
lets the seed metadata win.
"""
from __future__ import annotations

import re
from typing import Optional

from .models import DocumentType

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

# IRS filename grammar: (f|i|p)<product>[s<schedule>][gi]... e.g. f1040s1, i1040sc, i1040gi, p17, f1120ssk
IRS_FILE_RE = re.compile(
    r"^(?P<kind>[fip])(?P<prod>\d{1,5}[a-z]{0,3}?)(?:s(?P<sched>[a-z0-9]{1,3}))?(?P<gi>gi)?(?:--(?P<suffix>dft|\d{4}))?\.pdf$",
    re.I,
)

PRODUCT_RE = re.compile(
    r"^(?P<kind>Form|Instruction|Instructions|Publication|Publ|Notice)\s+(?P<num>[A-Z0-9\-]+)"
    r"(?:\s*\((?P<paren>[^)]*)\))?",
    re.I,
)
SCHED_IN_PAREN_RE = re.compile(r"Schedule\s+(?P<s>[A-Z0-9\-]+)", re.I)
SCHED_FORM_RE = re.compile(r"Schedule\s+(?P<s>[A-Z0-9\-]+)\s*\(Form\s+(?P<f>[A-Z0-9\-]+)\)", re.I)

DRAFT_TEXT_RE = re.compile(r"DRAFT AS OF|Do not file draft forms|This is an early release draft", re.I)


def parse_revision(text: str | None) -> tuple[Optional[int], Optional[str]]:
    """'2025' -> (2025, None); 'Jan 2024' -> (None, '01-2024'); '0622' -> (None, '06-2022')."""
    if not text:
        return None, None
    t = text.strip()
    if re.fullmatch(r"(19|20)\d{2}", t):
        return int(t), None
    m = re.fullmatch(r"([A-Za-z]{3})[a-z]*\.?\s+((?:19|20)\d{2})", t)
    if m and m.group(1).lower() in MONTHS:
        return None, f"{MONTHS[m.group(1).lower()]:02d}-{m.group(2)}"
    m = re.fullmatch(r"(0[1-9]|1[0-2])(\d{2})", t)
    if m:
        return None, f"{m.group(1)}-20{m.group(2)}"
    m = re.fullmatch(r"(0[1-9]|1[0-2])/((?:19|20)\d{2})", t)
    if m:
        return None, f"{m.group(1)}-{m.group(2)}"
    return None, None


def identify_irs_product(product: str, title: str = "") -> dict:
    """Map an irs.gov listing 'Product Number' + title to identity fields."""
    out: dict = {}
    m = PRODUCT_RE.match(product.strip())
    if not m:
        return out
    kind = m.group("kind").lower()
    num = m.group("num").upper()
    paren = m.group("paren") or ""
    sched = None
    sm = SCHED_IN_PAREN_RE.search(paren)
    if sm:
        sched = sm.group("s").upper()
    if kind.startswith("form"):
        out["document_type"] = DocumentType.schedule if sched else DocumentType.form
        out["form_number"] = num
    elif kind.startswith("instruction"):
        out["document_type"] = DocumentType.schedule_instructions if sched else DocumentType.instructions
        out["form_number"] = num
    elif kind.startswith("pub"):
        out["document_type"] = DocumentType.publication
        out["publication_number"] = num
    elif kind == "notice":
        out["document_type"] = DocumentType.notice
        out["form_number"] = num
    if sched:
        out["schedule"] = sched
    if title:
        out["title"] = re.sub(r"\s+", " ", title).strip()
    return out


def identify_irs_filename(filename: str) -> dict:
    """f1040s1.pdf -> schedule 1 of 1040; i1040gi.pdf -> 1040 instructions; p17.pdf -> pub 17."""
    m = IRS_FILE_RE.match(filename.lower())
    out: dict = {}
    if not m:
        return out
    kind, prod, sched = m.group("kind"), m.group("prod").upper(), m.group("sched")
    if m.group("suffix") == "dft":
        out["draft_or_final"] = "draft"
    elif m.group("suffix"):
        out["tax_year"] = int(m.group("suffix"))
    if kind == "p":
        out.update(document_type=DocumentType.publication, publication_number=prod)
    else:
        sched_u = sched.upper() if sched else None
        # 1120S is a product, not schedule S of 1120
        if prod == "1120" and sched_u and sched_u.startswith("S") and len(sched_u) > 1 and sched_u != "SK1":
            pass
        out["form_number"] = prod
        if sched_u:
            out["schedule"] = sched_u
            out["document_type"] = DocumentType.schedule if kind == "f" else DocumentType.schedule_instructions
        else:
            out["document_type"] = DocumentType.form if kind == "f" else DocumentType.instructions
    return out


def tax_types_for(form_number: str | None, schedule: str | None = None, title: str = "") -> list[str]:
    """Rough tax-type classification; collectors/seeds override."""
    if not form_number:
        f = ""
    else:
        f = form_number.upper()
    t = (title or "").lower()
    if f.startswith("1040") or f in {"W-2", "1099", "8949", "8962", "2441", "8812", "8863", "8995", "4562", "SE"} or "1040" in t:
        return ["1040"]
    if f.startswith("1065") or "1065" in t:
        return ["1065"]
    if f.startswith("1120S") or f.startswith("1120-S") or "1120-s" in t:
        return ["1120S"]
    if f.startswith("1120") or "1120" in t:
        return ["1120"]
    if f.startswith("1041") or "1041" in t:
        return ["1041"]
    if f.startswith("990") or "990" in t:
        return ["990"]
    return []


def detect_draft_in_text(first_pages_text: str) -> bool:
    return bool(DRAFT_TEXT_RE.search(first_pages_text or ""))


def guess_tax_year_from_text(first_page_text: str) -> Optional[int]:
    m = re.search(r"\b(20[12]\d)\b\s+(?:Instructions|Form|Schedule|Publication)", first_page_text or "")
    if m:
        return int(m.group(1))
    m = re.search(r"(?:Tax Year|For calendar year|For the year)\s+(20[12]\d)", first_page_text or "", re.I)
    if m:
        return int(m.group(1))
    return None
