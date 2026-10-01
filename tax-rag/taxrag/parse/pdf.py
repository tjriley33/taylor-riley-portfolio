"""Layout-aware PDF extraction with PyMuPDF.

Produces ordered Blocks per page (column-major reading order), joins wrapped
lines into paragraphs, de-hyphenates, and tags block kinds:
heading / line_heading / bullet / tip / caution / note / example / exception /
definition / table / worksheet / footer / para. Also returns the document
outline (bookmarks), embedded links, and per-page text coverage so OCR can be
decided per page.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from ..models import Block

LINE_HEAD_RE = re.compile(r"^(?:Lines?|Line)\s+(\d{1,3}[a-z]?(?:\s*(?:,|and|through|–|-)\s*\d{1,3}[a-z]?)*)\b", re.I)
MARKER_RE = re.compile(r"^(TIP|CAUTION!?|Note\.|Note:|Example\.|Example \d+\.|Exception\.|Exceptions\.|Worksheet|Definitions?\.)\s*", re.I)
BULLET_RE = re.compile(r"^[•●▪■\-–]\s+")
FOOTER_RE = re.compile(r"(Need more information or forms\? Visit IRS\.gov|^-\d+-$|^\d{1,3}$|^Page \d+ of \d+|^Cat\. No\.|^www\.irs\.gov|Instructions for .+ \(\d{4}\)$)", re.I)
HYPHEN_END_RE = re.compile(r"(\w)-$")
TABLE_WORDS = re.compile(r"\b(Worksheet|Table \d|TABLE \d)\b")


@dataclass
class PageExtraction:
    number: int
    blocks: list[Block]
    text_chars: int
    has_images_only: bool
    links: list[dict] = field(default_factory=list)


@dataclass
class PdfExtraction:
    path: str
    page_count: int
    metadata: dict
    outline: list[tuple[int, str, int]]        # (level, title, page 1-based)
    pages: list[PageExtraction]
    needs_ocr_pages: list[int]

    @property
    def first_pages_text(self) -> str:
        return "\n".join(b.text for p in self.pages[:3] for b in p.blocks)

    @property
    def body_font_size(self) -> float:
        from collections import Counter
        c: Counter = Counter()
        for p in self.pages:
            for b in p.blocks:
                if b.kind == "para":
                    c[round(b.font_size)] += len(b.text)
        return float(c.most_common(1)[0][0]) if c else 10.0


def _span_flags(span: dict) -> tuple[bool, bool]:
    font = span.get("font", "")
    flags = span.get("flags", 0)
    bold = bool(flags & 16) or "Bold" in font or "Black" in font or "Heavy" in font
    italic = bool(flags & 2) or "Italic" in font or "Oblique" in font
    return bold, italic


def _dehyphenate(lines: list[str]) -> str:
    out = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if not out:
            out = ln
            continue
        if HYPHEN_END_RE.search(out) and ln[:1].islower():
            out = out[:-1] + ln
        else:
            out = out + " " + ln
    return re.sub(r"\s+", " ", out).strip()


def _columns(blocks: list[dict], page_width: float) -> list[list[dict]]:
    """Cluster blocks into columns by x0. Handles 1, 2 or 3 column layouts."""
    if not blocks:
        return []
    xs = sorted(b["bbox"][0] for b in blocks)
    # simple gap clustering on x0
    clusters: list[list[float]] = [[xs[0]]]
    for x in xs[1:]:
        if x - clusters[-1][-1] > page_width * 0.12:
            clusters.append([x])
        else:
            clusters[-1].append(x)
    centers = [sum(c) / len(c) for c in clusters if len(c) >= 2] or [sum(c) / len(c) for c in clusters]
    cols: list[list[dict]] = [[] for _ in centers]
    for b in blocks:
        x0, x1 = b["bbox"][0], b["bbox"][2]
        if (x1 - x0) > page_width * 0.6:   # spans the page: treat as its own full-width row in col 0 but keep y
            b["_full"] = True
            cols[0].append(b)
            continue
        i = min(range(len(centers)), key=lambda k: abs(centers[k] - x0))
        cols[i].append(b)
    for c in cols:
        c.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))
    return cols


def extract_pdf(path: str | Path, ocr: bool = False) -> PdfExtraction:
    doc = pymupdf.open(str(path))
    outline = [(lvl, title.strip(), page) for lvl, title, page in doc.get_toc() if page > 0]
    pages: list[PageExtraction] = []
    needs_ocr: list[int] = []
    for pno in range(len(doc)):
        page = doc[pno]
        pe = _extract_page(page, pno + 1)
        if pe.text_chars < 40 and pe.has_images_only:
            needs_ocr.append(pno + 1)
            if ocr:
                try:
                    tp = page.get_textpage_ocr(full=True)
                    txt = page.get_text(textpage=tp)
                    pe.blocks = [Block(page=pno + 1, text=t.strip(), kind="para") for t in txt.split("\n\n") if t.strip()]
                    pe.text_chars = len(txt)
                except Exception:  # noqa: BLE001 - tesseract missing
                    pass
        pages.append(pe)
    meta = {k: v for k, v in (doc.metadata or {}).items() if v}
    doc.close()
    return PdfExtraction(path=str(path), page_count=len(pages), metadata=meta, outline=outline, pages=pages, needs_ocr_pages=needs_ocr)


def _extract_page(page: pymupdf.Page, pno: int) -> PageExtraction:
    d = page.get_text("dict")
    width = page.rect.width
    raw_blocks = [b for b in d["blocks"] if b.get("type") == 0 and b.get("lines")]
    images = [b for b in d["blocks"] if b.get("type") == 1]
    links = [{"page": pno, "uri": l.get("uri"), "to_page": (l.get("page", -1) + 1) if l.get("page") is not None else None,
              "bbox": tuple(round(x, 1) for x in l["from"])} for l in page.get_links() if l.get("uri") or l.get("page") is not None]
    cols = _columns(raw_blocks, width)
    blocks: list[Block] = []
    for col in cols:
        col = [part for rb in col for part in _split_runin(rb)]
        for rb in col:
            spans = [s for l in rb["lines"] for s in l["spans"] if s["text"].strip()]
            if not spans:
                continue
            line_texts = ["".join(s["text"] for s in l["spans"]) for l in rb["lines"]]
            text = _dehyphenate(line_texts)
            if not text:
                continue
            sizes = [s["size"] for s in spans]
            size = max(set(sizes), key=sizes.count)
            bold_chars = sum(len(s["text"]) for s in spans if _span_flags(s)[0])
            ital_chars = sum(len(s["text"]) for s in spans if _span_flags(s)[1])
            total = sum(len(s["text"]) for s in spans) or 1
            bold = bold_chars / total > 0.6
            italic = ital_chars / total > 0.6
            blk = Block(page=pno, text=text, font_size=round(size, 1), bold=bold, italic=italic,
                        bbox=tuple(round(x, 1) for x in rb["bbox"]))
            blocks.append(blk)
    _classify(blocks)
    text_chars = sum(len(b.text) for b in blocks)
    return PageExtraction(number=pno, blocks=blocks, text_chars=text_chars, has_images_only=bool(images) and text_chars < 40, links=links)


def _split_runin(rb: dict) -> list[dict]:
    """Split a block whose first line opens with a short bold lead ("Line 1", "Part I. Income") followed by
    regular text. PyMuPDF merges run-in headings with their paragraph; without the split the heading can't anchor."""
    lines = rb.get("lines") or []
    if not lines:
        return [rb]
    spans = [sp for sp in lines[0]["spans"] if sp["text"].strip()]
    if not spans or not _span_flags(spans[0])[0]:
        return [rb]
    lead, i = "", 0
    while i < len(spans) and _span_flags(spans[i])[0] and len(lead) < 100:
        lead += spans[i]["text"]; i += 1
    rest_first = "".join(sp["text"] for sp in spans[i:]).strip()
    rest_lines = lines[1:]
    rest_len = len(rest_first) + sum(len(sp["text"]) for l in rest_lines for sp in l["spans"])
    lead = lead.strip()
    if not lead or len(lead) >= 100 or rest_len < 40 or i == len(spans) and not rest_lines:
        return [rb]
    if not (LINE_HEAD_RE.match(lead) or re.match(r"^(Part|Section|Step|Column|Schedule|Worksheet|Example|Note|Caution|Tip|Exception)\b", lead, re.I)
            or lead.endswith(".") or lead.endswith(":")):
        return [rb]
    head_line = {"spans": spans[:i], "bbox": lines[0]["bbox"]}
    rest_spans = spans[i:]
    new_lines = ([{"spans": rest_spans, "bbox": lines[0]["bbox"]}] if rest_spans else []) + rest_lines
    head = {"bbox": rb["bbox"], "lines": [head_line], "type": 0}
    body = {"bbox": rb["bbox"], "lines": new_lines, "type": 0}
    return [head, body]


def _classify(blocks: list[Block]) -> None:
    """Assign kinds using font/size/bold and lexical markers. Merges marker-only blocks (TIP/CAUTION) into the following block."""
    if not blocks:
        return
    sizes = [b.font_size for b in blocks if len(b.text) > 40]
    body = max(set(sizes), key=sizes.count) if sizes else 10.0
    pending_marker: str | None = None
    for b in blocks:
        t = b.text
        if FOOTER_RE.search(t) and len(t) < 90:
            b.kind = "footer"
            continue
        m = MARKER_RE.match(t)
        if m and len(t) <= len(m.group(0)) + 2:
            pending_marker = m.group(1).lower().rstrip("!.:")
            b.kind = "marker"
            continue
        lm = LINE_HEAD_RE.match(t)
        heading_like = b.bold and len(t) < 160 and not t.endswith(".") and (b.font_size >= body + 1.5 or bool(lm))
        if pending_marker and not heading_like:
            # TIP/CAUTION icon sits beside an italic paragraph; attach the marker to that paragraph, never to a heading.
            b.kind = {"tip": "tip", "caution": "caution", "note": "note", "example": "example", "exception": "exception",
                      "exceptions": "exception", "worksheet": "worksheet", "definition": "definition", "definitions": "definition"}.get(pending_marker.split()[0], "note")
            pending_marker = None
            continue
        if lm and b.bold and len(t) < 120:
            b.kind = "line_heading"
            b.line_ref = lm.group(1).replace(" ", "")
            b.level = 3
            continue
        if b.bold and len(t) < 160 and not t.endswith(".") and b.font_size >= body + 1.5:
            b.kind = "heading"
            b.level = 1 if b.font_size >= body + 3.5 else 2
            continue
        if b.bold and len(t) < 120 and not t.endswith("."):
            b.kind = "heading"
            b.level = 3
            continue
        if BULLET_RE.match(t):
            b.kind = "bullet"
            continue
        if m:
            key = m.group(1).lower().rstrip("!.:").split()[0]
            b.kind = {"tip": "tip", "caution": "caution", "note": "note", "example": "example", "exception": "exception",
                      "exceptions": "exception", "worksheet": "worksheet", "definition": "definition", "definitions": "definition"}.get(key, "note")
            continue
        if TABLE_WORDS.search(t) and len(t) < 100 and b.bold:
            b.kind = "worksheet"
            continue
        b.kind = "para"
    # drop marker-only blocks
    blocks[:] = [b for b in blocks if b.kind != "marker"]
