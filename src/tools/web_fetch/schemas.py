"""Pydantic v2 schemas for the ``web_fetch`` tool (spec §5).

One result shape for every source: PDF / HTML / text all fill the same
``FetchResult``; source-specific fields are simply left ``None`` / empty. These
models are the contract between the deterministic pipeline and the agent — the
handler serialises ``FetchResult`` to JSON and hands it back (see ``tool.py``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# Fixed access contract surfaced on every result (spec §5.6). Not a per-doc hint —
# it tells the agent *how* to consume what the tool staged.
USAGE = (
    "Use the Read tool on content_path to view the content. "
    "Figures are referenced inline by local path — Read those files to view them. "
    "If content_inline is set, the content is small and included; no Read needed. "
    "Data files in `links` (type=data) are not downloaded — fetch any you need "
    "yourself with the Bash tool (e.g. curl)."
)


class WebFetchInput(BaseModel):
    """Tool input (spec §5.1). Named distinctly from the tool so it doesn't read
    as a clash with the removed built-in ``WebFetch``."""

    url: str
    force_raw: bool = False  # skip trafilatura main-content extraction


class Link(BaseModel):
    """Typed link from the full-DOM harvest (spec §5.2)."""

    url: str
    text: str | None = None
    type: Literal[
        "data", "citation", "nav", "external", "self", "alternate_pdf", "chrome"
    ]
    mime_hint: str | None = None  # csv, dat, nml, inp, vtk, foam, msh, h5, ...


class FigureRef(BaseModel):
    """HTML figure index entry (spec §5.3). ``image_path`` is an absolute local
    path iff the image was downloaded — Read can view it directly."""

    id: str
    caption: str | None = None
    src_url: str | None = None
    image_path: str | None = None


class TableRef(BaseModel):
    """Thin table index (spec §5.3). The table markdown itself lives inline in
    ``content.md``; this only points at it."""

    id: str
    caption: str | None = None
    line: int | None = None  # start line in content.md
    n_rows: int = 0
    n_cols: int = 0


class TocEntry(BaseModel):
    """Navigation map entry — page-anchored (PDF) or line-anchored (HTML/text)
    so the agent can aim Read directly (spec §5.4)."""

    id: int
    title: str
    level: int | None = None
    # PDF locator → feeds Read `pages` (respect the 20-page/call cap):
    page: int | None = None  # 1-indexed start
    page_end: int | None = None
    # HTML/text locator → feeds Read `offset`/`limit` on content_path:
    line: int | None = None  # 1-indexed start line in content.md
    line_end: int | None = None
    est_tokens: int | None = None


class DocMetadata(BaseModel):
    """Deterministic document metadata (spec §5.5)."""

    source_url: str
    resolved_url: str | None = None
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    date: str | None = None
    doi: str | None = None
    venue: str | None = None
    abstract: str | None = None
    language: str | None = None
    accessed: str | None = None  # ISO date of this fetch
    page_kind: (
        Literal["article", "doc", "forum", "index", "dataset", "unknown"] | None
    ) = None
    alternate_pdf_url: str | None = None


class FetchResult(BaseModel):
    """The handoff descriptor (spec §5.6) — points the agent at a staged file plus
    a navigation map; it is not the extracted content itself."""

    status: Literal[
        "ok",
        "redirected",
        "blocked_by_robots",
        "oversize",
        "binary_skipped",
        "fetch_error",
        "parse_error",
    ]
    content_type: Literal["pdf", "html", "text"] | None = None

    content_path: str | None = None  # absolute: source.pdf | content.md | content.txt
    content_inline: str | None = None  # small docs only
    usage: str = USAGE

    metadata: DocMetadata
    toc: list[TocEntry] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)
    figures: list[FigureRef] = Field(default_factory=list)
    tables: list[TableRef] = Field(default_factory=list)

    page_count: int | None = None  # PDF
    line_count: int | None = None  # html/text content
    est_tokens: int | None = None  # whole-doc size hint (NOT a gate)

    redirect_url: str | None = None  # status == "redirected"
    content_length: int | None = None  # status in {oversize, binary_skipped}
    error: str | None = None  # short reason when status in {fetch_error, parse_error}
