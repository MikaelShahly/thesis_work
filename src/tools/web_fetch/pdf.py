"""PDF stager + cheap structural pass (spec §4.4).

Stages ``source.pdf`` and runs a no-parse pypdf pass: page count, embedded URI
link annotations, embedded metadata (best-effort), and a TOC built by a cheap
ladder — embedded outline first, then a numbered-heading regex. No content parse,
no OCR, no rasterization. Font-size clustering (ladder step 3) is deferred polish;
an empty TOC is acceptable (the agent reads from page 1).
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from pypdf import PdfReader

from src.tools.web_fetch.classify import classify_link
from src.tools.web_fetch.fetcher import FetchOutcome
from src.tools.web_fetch.schemas import DocMetadata, FetchResult, Link, TocEntry

# pypdf logs recoverable-malformation warnings ("Multiple definitions … /Length")
# per object — noisy and harmless. Quiet them; real failures still raise/return.
logging.getLogger("pypdf").setLevel(logging.ERROR)

_MAX_SECTION_NO = 40  # section numbers are small; reject page-number / header noise

# Numbered section line: "3.2 Boundary Conditions" (spec §4.4 ladder step 2).
_NUMBERED = re.compile(r"^(\d+(?:\.\d+){0,3})\s+([A-Z][^\n]{2,80})$")
# Cap the numbered-heading text scan: outline covers books/theses; the regex
# fallback mainly serves short outline-less papers. Bounds pathological cost.
_NUMBERED_MAX_PAGES = 60


async def process(
    outcome: FetchOutcome, entry: Path, accessed: str, source_url: str
) -> FetchResult:
    pdf_path = entry / "source.pdf"
    pdf_path.write_bytes(outcome.raw or b"")

    meta = DocMetadata(
        source_url=source_url, resolved_url=outcome.resolved_url, accessed=accessed
    )
    result = FetchResult(
        status="ok",
        content_type="pdf",
        content_path=str(pdf_path.resolve()),
        metadata=meta,
    )

    try:
        reader = PdfReader(str(pdf_path))
    except Exception:
        return result  # staged but unparseable — agent still Reads pages directly

    try:
        result.page_count = len(reader.pages)
    except Exception:
        pass

    _fill_metadata(reader, meta)
    base_host = urlsplit(source_url).hostname or ""
    result.links = _harvest_links(reader, base_host)
    result.toc = _outline_toc(reader) or _numbered_toc(reader)
    return result


def _fill_metadata(reader: PdfReader, meta: DocMetadata) -> None:
    """Embedded XMP/Info is frequently junk; set only obviously-real fields. The
    agent already holds citation identity from the web_search that led here."""
    try:
        info = reader.metadata
    except Exception:
        return
    if not info:
        return
    title = (info.title or "").strip() if info.title else ""
    if title:
        meta.title = title
    author = (info.author or "").strip() if info.author else ""
    if author:
        meta.authors = [a.strip() for a in re.split(r"[;,]| and ", author) if a.strip()]


def _harvest_links(reader: PdfReader, base_host: str) -> list[Link]:
    out: list[Link] = []
    seen: set[str] = set()
    for page in reader.pages:
        try:
            annots = page.get("/Annots") or []
        except Exception:
            continue
        for a in annots:
            try:
                obj = a.get_object()
                uri = (obj.get("/A") or {}).get("/URI")
                if not uri:
                    continue
                uri = str(uri)
                if uri in seen:
                    continue
                seen.add(uri)
                tagged = classify_link(uri, base_host=base_host)
                if tagged is None:
                    continue
                out.append(Link(url=uri, type=tagged[0], mime_hint=tagged[1]))
            except Exception:
                continue
    return out


def _outline_toc(reader: PdfReader) -> list[TocEntry]:
    out: list[TocEntry] = []
    counter = [0]

    def walk(items, level: int) -> None:
        for it in items:
            if isinstance(it, list):
                walk(it, level + 1)
                continue
            try:
                title = (getattr(it, "title", "") or "").strip()
                if not title:
                    continue
                page0 = reader.get_destination_page_number(it)  # 0-indexed
                counter[0] += 1
                out.append(
                    TocEntry(id=counter[0], title=title, level=level, page=page0 + 1)
                )
            except Exception:
                continue  # one malformed bookmark must not sink the whole TOC

    try:
        walk(reader.outline, 1)
    except Exception:
        return []

    # page_end = the next entry's start page (helps the agent size Read ranges).
    for i, e in enumerate(out):
        nxt = next((o.page for o in out[i + 1:] if o.page), None)
        if nxt and nxt >= (e.page or 0):
            e.page_end = nxt
    return out


def _numbered_toc(reader: PdfReader) -> list[TocEntry]:
    # Heuristic, noise-prone on scans (per spec) — filter hard so junk yields an
    # empty TOC rather than misleading entries. Candidates must have a small
    # section number, a mostly-alphabetic title, and a title that doesn't repeat
    # across pages (running headers repeat; real sections are unique).
    cand: list[tuple[str, str, int]] = []
    for i, page in enumerate(reader.pages[:_NUMBERED_MAX_PAGES]):
        try:
            txt = page.extract_text() or ""
        except Exception:
            continue
        for line in txt.splitlines():
            m = _NUMBERED.match(line.strip())
            if not m:
                continue
            num, title = m.group(1), m.group(2).strip()
            if int(num.split(".")[0]) > _MAX_SECTION_NO:
                continue
            letters = sum(c.isalpha() for c in title)
            if letters < 3 or letters < 0.5 * len(title.replace(" ", "")):
                continue  # OCR noise like "V 1 1 V _-"
            cand.append((num, title, i + 1))

    repeats = Counter(t for _, t, _ in cand)
    out: list[TocEntry] = []
    for num, title, page in cand:
        if repeats[title] > 1:
            continue  # running header / footer, not a section
        out.append(
            TocEntry(
                id=len(out) + 1,
                title=f"{num} {title}",
                level=num.count(".") + 1,
                page=page,
            )
        )
    return out
