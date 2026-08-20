"""HTML extractor (spec §4.5): one lxml DOM parse → three **independent** passes
→ assemble.

The passes don't gate each other: a content-extraction miss never costs links or
images. That's what makes "capture all data links" a guarantee (Pass 1) rather than
a hope. Pass 1 = link harvest + classify; Pass 2 = image harvest + download;
Pass 3 = content → markdown (trafilatura, precision-leaning, with a thin-extraction
fallback and a generic repeated-block dedup). Assembly writes ``content.md``,
rewrites downloaded-figure srcs to absolute local paths, and builds a line-anchored
TOC the agent drives Read with.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from copy import deepcopy
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
import trafilatura
from lxml import html as lxml_html
from markdownify import markdownify

from src.tools.web_fetch.classify import IMAGE_SIGNAL_WORDS, classify_link
from src.tools.web_fetch.fetcher import USER_AGENT, FetchOutcome, _host_is_safe_async
from src.tools.web_fetch.schemas import (
    DocMetadata,
    FetchResult,
    FigureRef,
    Link,
    TableRef,
    TocEntry,
)
from src.tools.web_fetch.text import SMALL_DOC_LINES

FIGURE_CAP = 25
MAX_IMAGE_CANDIDATES = 80
IMAGE_TIMEOUT_S = 15.0
MAX_IMAGE_BYTES = 10 * 1024 * 1024
THIN_RATIO = 0.25  # extracted < 25% of visible text → fallback
CHROME_TAGS = {"nav", "header", "footer", "aside"}
CHROME_ROLES = {"navigation", "banner", "contentinfo", "complementary"}
DEDUP_MIN_REPEAT = 4
DEDUP_MAX_BLOCK_CHARS = 200

_TOKEN = re.compile(r"[a-z0-9]+")
_IMG_MD = re.compile(r"(!\[[^\]]*\]\()([^)\s]+)([^)]*\))")
_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
# Heading permalink anchors that doc generators append (Antora/Sphinx/MkDocs):
# "## Overview[🔗](#overview)" → "## Overview". Only strips a trailing #-anchor link.
_HEADING_ANCHOR = re.compile(r"^(#{1,6}\s+.*?)\s*\[[^\]]*\]\(#[^)]*\)\s*$", re.M)
_CT_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}


async def process(
    outcome: FetchOutcome,
    entry: Path,
    accessed: str,
    source_url: str,
    force_raw: bool = False,
) -> FetchResult:
    raw = outcome.raw or b""
    html_text = raw.decode(outcome.encoding or "utf-8", errors="replace")
    try:
        dom = lxml_html.fromstring(raw)
    except Exception:
        try:
            dom = lxml_html.fromstring(html_text)
        except Exception:
            dom = None

    base_url = _resolve_base(dom, outcome.resolved_url)
    base_host = urlsplit(base_url).hostname or ""

    # Pass 1 + Pass 2 over the ORIGINAL dom — the platform-independent guarantees.
    links = _harvest_links(dom, base_url, base_host) if dom is not None else []
    candidates = _collect_images(dom, base_url) if dom is not None else []
    figures = await _download_figures(candidates, entry)

    # Pass 3 — content → markdown. Pull code blocks out to sentinels on a COPY
    # first (trafilatura mangles <pre>), extract prose, then restore code verbatim
    # as fenced blocks. Link/image harvest above used the untouched original dom.
    md_dom = dom
    code_blocks: dict[str, str] = {}
    if dom is not None:
        md_dom = deepcopy(dom)
        code_blocks = _extract_code_blocks(md_dom)
        html_text = lxml_html.tostring(md_dom, encoding="unicode")
    md = _extract_markdown(html_text, md_dom, base_url, force_raw)
    if code_blocks:
        md = _restore_code_blocks(md, code_blocks)
    md = _inline_figures(md, figures, base_url)
    md = _HEADING_ANCHOR.sub(r"\1", md)  # drop doc-generator heading permalinks
    md = _append_figure_gallery(md, figures)  # surface table-cell plots Read-ably

    content_path = entry / "content.md"
    content_path.write_text(md)
    line_count = md.count("\n") + 1 if md else 0

    meta = _extract_metadata(html_text, dom, source_url, outcome.resolved_url, accessed)
    meta.page_kind = _guess_page_kind(dom, html_text, links, source_url)

    return FetchResult(
        status="ok",
        content_type="html",
        content_path=str(content_path.resolve()),
        content_inline=md if line_count <= SMALL_DOC_LINES else None,
        metadata=meta,
        toc=_line_anchored_toc(md),
        links=links,
        figures=figures,
        tables=_table_refs(md),
        line_count=line_count,
        est_tokens=len(md) // 4,
    )


# ── base URL ──────────────────────────────────────────────────────────────
def _resolve_base(dom, resolved_url: str) -> str:
    if dom is not None:
        try:
            b = dom.find(".//base[@href]")
            if b is not None and b.get("href"):
                return urljoin(resolved_url, b.get("href"))
        except Exception:
            pass
    return resolved_url


def _in_chrome(el) -> bool:
    for anc in el.iterancestors():
        tag = anc.tag
        if isinstance(tag, str) and tag.lower() in CHROME_TAGS:
            return True
        if (anc.get("role") or "").lower() in CHROME_ROLES:
            return True
    return False


# ── Pass 1: link harvest + classify ─────────────────────────────────────────
def _harvest_links(dom, base_url: str, base_host: str) -> list[Link]:
    out: list[Link] = []
    seen: set[str] = set()
    candidates: list[tuple] = []
    for el in dom.iter("a"):
        href = el.get("href")
        if href:
            candidates.append((el, href, (el.text_content() or "").strip()[:200]))
    for el in dom.iter("link"):
        href = el.get("href")
        if href:
            candidates.append((el, href, None))
    for tag in ("source", "embed"):
        for el in dom.iter(tag):
            src = el.get("src") or el.get("data-src")
            if src:
                candidates.append((el, src, None))
    for el in dom.iter("object"):
        if el.get("data"):
            candidates.append((el, el.get("data"), None))

    for el, href, text in candidates:
        try:
            abs_url = urljoin(base_url, href)
        except Exception:
            continue
        if abs_url in seen:
            continue
        tagged = classify_link(
            abs_url, text=text, in_chrome=_in_chrome(el), base_host=base_host
        )
        if tagged is None:
            continue
        seen.add(abs_url)
        out.append(
            Link(url=abs_url, text=text or None, type=tagged[0], mime_hint=tagged[1])
        )
    return out


# ── Pass 2: image harvest + region-aware filter + download ──────────────────
def _signal_hit(el, url: str) -> bool:
    blob = " ".join(
        filter(None, [url, el.get("class"), el.get("alt"), el.get("id")])
    ).lower()
    return bool(set(_TOKEN.findall(blob)) & IMAGE_SIGNAL_WORDS)


def _int(v) -> int | None:
    try:
        return int(re.sub(r"[^\d]", "", v)) if v else None
    except (TypeError, ValueError):
        return None


def _anchor_decoration(el) -> bool:
    """An <img> whose nearest <a> ancestor targets a same-page anchor (``#...``) —
    skip-to-content links, heading-anchor icons. Decoration, not content."""
    for anc in el.iterancestors():
        if isinstance(anc.tag, str) and anc.tag.lower() == "a":
            return (anc.get("href") or "").strip().startswith("#")
    return False


def _is_math_alt(alt: str) -> bool:
    """alt is rendered LaTeX (an inline equation image). Old physics sites — e.g.
    the NASA TMR — render every equation as a small PNG with the LaTeX in `alt`
    (``\\tau_{ij}=…``, ``c_2=0.7``, ``k_s``). The alt text *is* the content (kept
    inline in the markdown), so don't download the glyph or spend a figure slot on
    it — otherwise hundreds of equation images exhaust the cap and crowd out the
    real plots/sketches. The markup chars ``\\ { } _ ^`` (commands, sub/superscripts)
    flag LaTeX; real figure captions are prose and contain none. Images with a
    descriptive or empty alt (e.g. an equation rendered with no LaTeX alternative)
    are NOT flagged — there the image is the only representation, so it's kept."""
    return any(c in alt for c in "\\{}_^")


def _keep_image(el, url: str) -> bool:
    if url.lower().startswith("data:"):
        return False
    if _anchor_decoration(el):
        return False
    if _signal_hit(el, url):
        return False
    alt = (el.get("alt") or "").strip()
    if alt and not any(c.isalnum() for c in alt):
        return False  # glyph/UI icon (Doxygen "-"/"+", arrows) — never content
    if _is_math_alt(alt):
        return False  # equation image — its LaTeX alt stays inline as text
    w, h = _int(el.get("width")), _int(el.get("height"))
    if w == 1 or h == 1:
        return False
    if _in_chrome(el):  # aggressive in chrome: drop small/icon-sized
        if (w is not None and w < 100) or (h is not None and h < 100):
            return False
    return True  # content flow: bias to over-keep (Read judges relevance)


def _collect_images(dom, base_url: str) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for img in dom.iter("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        if not src:
            continue
        try:
            abs_url = urljoin(base_url, src)
        except Exception:
            continue
        if abs_url in seen or not _keep_image(img, abs_url):
            continue
        seen.add(abs_url)
        cap = (img.get("alt") or img.get("title") or "").strip() or None
        out.append((abs_url, cap))
        if len(out) >= MAX_IMAGE_CANDIDATES:
            break
    return out


def _img_ext(ct: str, url: str) -> str | None:
    for k, v in _CT_EXT.items():
        if k in ct:
            return v
    last = urlsplit(url).path.rsplit("/", 1)[-1]
    e = last.rsplit(".", 1)[-1].lower() if "." in last else ""
    if e in ("png", "gif", "webp"):
        return e
    if e in ("jpg", "jpeg"):
        return "jpg"
    return None  # unknown / non-raster (e.g. svg) — skip download


async def _download_figures(
    candidates: list[tuple[str, str | None]], entry: Path
) -> list[FigureRef]:
    figs: list[FigureRef] = []
    sem = asyncio.Semaphore(6)

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, timeout=IMAGE_TIMEOUT_S, follow_redirects=True
    ) as client:

        async def dl(i: int, url: str, cap: str | None) -> FigureRef | None:
            host = urlsplit(url).hostname or ""
            if not host or not await _host_is_safe_async(host):
                return None
            async with sem:
                try:
                    r = await client.get(url)
                except httpx.HTTPError:
                    return None
            if r.status_code >= 400:
                return None
            ext = _img_ext(r.headers.get("content-type", "").lower(), url)
            if ext is None or not r.content or len(r.content) > MAX_IMAGE_BYTES:
                return None
            p = entry / "figures" / f"fig-{i}.{ext}"
            try:
                p.write_bytes(r.content)
            except OSError:
                return None
            return FigureRef(
                id=f"fig-{i}", caption=cap, src_url=url, image_path=str(p.resolve())
            )

        results = await asyncio.gather(
            *(dl(i + 1, u, c) for i, (u, c) in enumerate(candidates[:FIGURE_CAP]))
        )
    return [r for r in results if r is not None]


def _inline_figures(md: str, figures: list[FigureRef], base_url: str) -> str:
    by_abs = {f.src_url: f.image_path for f in figures if f.image_path and f.src_url}
    if not by_abs:
        return md

    def repl(m: re.Match) -> str:
        try:
            absu = urljoin(base_url, m.group(2))
        except Exception:
            return m.group(0)
        local = by_abs.get(absu)
        return f"{m.group(1)}{local}{m.group(3)}" if local else m.group(0)

    return _IMG_MD.sub(repl, md)


def _append_figure_gallery(md: str, figures: list[FigureRef]) -> str:
    """Append a "## Figures" section embedding any downloaded figure not already
    referenced in ``md``. trafilatura drops images that sit in table cells (common
    on TMR results pages), so without this most plots would live only in the
    ``figures`` index; this makes content.md self-contained — every figure is
    Read-able from the markdown the agent already opens."""
    missing = [f for f in figures if f.image_path and f.image_path not in md]
    if not missing:
        return md
    out = [md.rstrip("\n"), "", "## Figures", ""]
    for f in missing:
        cap = (f.caption or f.id).replace("\n", " ").replace("]", " ").strip()
        out.append(f"![{cap}]({f.image_path})")
        out.append("")
    return "\n".join(out) + "\n"


# ── Pass 3: content → markdown ───────────────────────────────────────────────
def _by_class(root, token: str):
    q = f'contains(concat(" ", normalize-space(@class), " "), " {token} ")'
    return root.xpath(f".//*[{q}]")


def _line_text(ln) -> str:
    # Blank the Doxygen line-number gutter in place. Don't .remove() it —
    # lxml drops an element's tail with it, and the code is often that tail.
    for no in _by_class(ln, "lineno"):
        no.text = ""
        for child in list(no):
            no.remove(child)
    return ln.text_content().replace("\xa0", " ").rstrip()


_CODE_SENTINEL = "xwfcode{}endx"  # alnum, single-line: survives both extractors intact


def _extract_code_blocks(dom) -> dict[str, str]:
    """Replace every code container — existing ``<pre>`` and Doxygen ``.fragment``
    line-soup — with a one-line sentinel ``<pre>``, returning
    ``{sentinel: verbatim_code}``. trafilatura otherwise **collapses ``<pre>``
    newlines and never fences**; restoring the captured text as fenced blocks
    afterwards guarantees code survives verbatim on both the trafilatura and the
    markdownify fallback paths (OpenFOAM dictionaries, Doxygen source, forum
    pastes)."""
    targets: list[tuple] = []
    for frag in _by_class(dom, "fragment"):
        lines = _by_class(frag, "line")
        code = (
            "\n".join(_line_text(ln) for ln in lines)
            if lines
            else frag.text_content().replace("\xa0", " ")
        )
        targets.append((frag, code))
    for pre in dom.xpath(".//pre"):
        targets.append((pre, pre.text_content()))

    blocks: dict[str, str] = {}
    for el, code in targets:
        if not code.strip() or el.getparent() is None:
            continue
        key = _CODE_SENTINEL.format(len(blocks))
        ph = lxml_html.Element("pre")
        ph.text = key
        ph.tail = el.tail
        el.getparent().replace(el, ph)
        blocks[key] = code
    return blocks


def _restore_code_blocks(md: str, blocks: dict[str, str]) -> str:
    for key, code in blocks.items():
        fenced = "```\n" + code.strip("\n") + "\n```"
        md = md.replace(f"```\n{key}\n```", fenced)  # markdownify fenced the sentinel
        md = md.replace(key, fenced)  # trafilatura left it bare
    return md


def _extract_markdown(html_text: str, dom, base_url: str, force_raw: bool) -> str:
    md = None
    if not force_raw:
        try:
            md = trafilatura.extract(
                html_text,
                output_format="markdown",
                include_comments=True,
                include_tables=True,
                include_formatting=True,
                include_links=True,
                include_images=True,
                favor_recall=False,
                url=base_url,
                with_metadata=False,
            )
        except Exception:
            md = None

    if (force_raw or not md or _is_thin(md, dom)) and dom is not None:
        fallback = _cleaned_dom_markdown(dom)
        if force_raw or not md or (fallback and len(fallback) > len(md or "")):
            md = fallback or md or ""

    return _dedup_repeated_blocks((md or "").strip()) + "\n"


def _is_thin(md: str, dom) -> bool:
    if dom is None:
        return False
    try:
        total = len(" ".join(dom.text_content().split()))
    except Exception:
        return False
    return total >= 500 and len(md) < THIN_RATIO * total


def _cleaned_dom_markdown(dom) -> str:
    try:
        d = deepcopy(dom)
        for tag in (
            "script", "style", "noscript", "nav", "header",
            "footer", "aside", "form", "svg",
        ):
            for el in list(d.iter(tag)):
                if el.getparent() is not None:
                    el.drop_tree()
        root = d.find(".//main")
        if root is None:
            root = d.find(".//body")
        if root is None:
            root = d
        return markdownify(
            lxml_html.tostring(root, encoding="unicode"),
            heading_style="ATX",
            code_language="",
        )
    except Exception:
        return ""


def _dedup_repeated_blocks(md: str) -> str:
    """Collapse short text lines that recur across the page (forum signatures,
    'Reply With Quote' buttons). Conservative: ≥4 repeats, has a letter, not a
    table/heading/code-fence line."""
    lines = md.split("\n")

    def eligible(s: str) -> bool:
        return (
            0 < len(s) <= DEDUP_MAX_BLOCK_CHARS
            and not s.startswith(("|", "#", "```", ">"))
            and any(c.isalpha() for c in s)
        )

    counts = Counter(s for ln in lines if eligible(s := ln.strip()))
    repeated = {s for s, c in counts.items() if c >= DEDUP_MIN_REPEAT}
    if not repeated:
        return md
    seen: set[str] = set()
    out: list[str] = []
    for ln in lines:
        s = ln.strip()
        if s in repeated:
            if s in seen:
                continue
            seen.add(s)
        out.append(ln)
    return "\n".join(out)


# ── metadata ─────────────────────────────────────────────────────────────────
def _meta_map(dom) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if dom is None:
        return out
    for m in dom.iter("meta"):
        key = (m.get("name") or m.get("property") or "").strip().lower()
        content = m.get("content")
        if key and content:
            out.setdefault(key, []).append(content.strip())
    return out


def _extract_metadata(
    html_text: str, dom, source_url: str, resolved_url: str, accessed: str
) -> DocMetadata:
    meta = DocMetadata(
        source_url=source_url, resolved_url=resolved_url, accessed=accessed
    )
    try:
        doc = trafilatura.extract_metadata(html_text)
    except Exception:
        doc = None
    if doc is not None:
        meta.title = getattr(doc, "title", None) or None
        author = getattr(doc, "author", None)
        if author:
            meta.authors = [a.strip() for a in re.split(r"[;,]", author) if a.strip()]
        meta.date = getattr(doc, "date", None) or None
        meta.abstract = getattr(doc, "description", None) or None
        meta.venue = getattr(doc, "sitename", None) or None

    tags = _meta_map(dom)

    def first(*names: str) -> str | None:
        for n in names:
            if tags.get(n):
                return tags[n][0]
        return None

    title = first("citation_title", "og:title", "dc.title")
    if title:
        meta.title = title
    if not meta.title and dom is not None:
        meta.title = (dom.findtext(".//title") or "").strip() or None

    authors = tags.get("citation_author") or tags.get("dc.creator")
    if authors:
        meta.authors = authors

    meta.doi = (first("citation_doi") or "").replace("doi:", "").strip() or None
    meta.date = (
        first(
            "citation_date",
            "citation_publication_date",
            "article:published_time",
            "dc.date",
        )
        or meta.date
    )
    meta.venue = first("citation_journal_title") or meta.venue
    meta.abstract = (
        first("citation_abstract", "og:description", "description") or meta.abstract
    )
    meta.alternate_pdf_url = first("citation_pdf_url") or _alt_pdf_link(dom, resolved_url)
    if dom is not None:
        meta.language = (dom.get("lang") or "").strip() or None
    return meta


def _alt_pdf_link(dom, resolved_url: str) -> str | None:
    if dom is None:
        return None
    for ln in dom.iter("link"):
        rel = (ln.get("rel") or "").lower()
        typ = (ln.get("type") or "").lower()
        if "alternate" in rel and "pdf" in typ and ln.get("href"):
            try:
                return urljoin(resolved_url, ln.get("href"))
            except Exception:
                return ln.get("href")
    return None


def _guess_page_kind(dom, html_text: str, links: list[Link], url: str) -> str:
    low = url.lower()
    if any(s in low for s in ("/forum", "showthread", "viewtopic", "/threads/", "/t/")):
        return "forum"
    if "doxygen" in html_text[:3000].lower():
        return "doc"
    data_links = sum(1 for ln in links if ln.type == "data")
    if data_links >= 8:
        return "index"
    if dom is not None and dom.find(".//article") is not None:
        return "article"
    return "unknown"


# ── navigation map + tables ──────────────────────────────────────────────────
def _line_anchored_toc(md: str) -> list[TocEntry]:
    lines = md.split("\n")
    raw = [
        (m.group(2).strip(), len(m.group(1)), i)
        for i, line in enumerate(lines, start=1)
        if (m := _HEADING.match(line))
    ]
    # Drop forum/post noise: a heading that is just a link (post-author headings,
    # e.g. "[sergiu tofanel](/members/…)") or one that repeats many times across
    # the page (per-post meta like "Well-Known Member") is not a real section.
    counts = Counter(t for t, _, _ in raw)
    entries: list[TocEntry] = []
    for title, level, line in raw:
        if re.fullmatch(r"\[[^\]]*\]\([^)]*\)", title) or counts[title] > 3:
            continue
        entries.append(
            TocEntry(id=len(entries) + 1, title=title, level=level, line=line)
        )
    for j, e in enumerate(entries):
        e.line_end = entries[j + 1].line - 1 if j + 1 < len(entries) else len(lines)
        seg = "\n".join(lines[(e.line or 1) - 1 : e.line_end])
        e.est_tokens = len(seg) // 4
    return entries


def _table_refs(md: str) -> list[TableRef]:
    lines = md.split("\n")
    out: list[TableRef] = []
    i = 0
    while i < len(lines) - 1:
        header, sep = lines[i].strip(), lines[i + 1].strip()
        is_sep = bool(re.match(r"^\|?[\s:|-]+\|?$", sep)) and "-" in sep
        if header.startswith("|") and is_sep:
            n_cols = max(header.count("|") - 1, 1)
            j = i + 2
            n_rows = 0
            while j < len(lines) and lines[j].strip().startswith("|"):
                n_rows += 1
                j += 1
            out.append(
                TableRef(
                    id=f"table-{len(out) + 1}",
                    line=i + 1,
                    n_rows=n_rows,
                    n_cols=n_cols,
                )
            )
            i = j
        else:
            i += 1
    return out
