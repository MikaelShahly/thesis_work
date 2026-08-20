"""Pydantic v2 schemas for the ``paper_search`` tool.

One result shape across every source: OpenAlex / arXiv / NTRS / Semantic Scholar
all fill the same ``PaperHit``; source-specific gaps are simply left ``None``
(e.g. arXiv and NTRS carry no ``citations`` — they aren't citation indexes).

The tool's whole job is to hand back candidates that carry a **direct,
fetchable** ``pdf_url`` so the agent can pipe the chosen ones straight into
``web_fetch`` → ``Read``. It does NOT fetch or summarise; ``abstract`` is a
triage signal, not the answer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Fixed consumption contract surfaced on every result. Tells the agent how to
# turn a hit into actual content: the search finds papers; web_fetch fetches.
USAGE = (
    "These are search candidates, not content. To read a paper, take its "
    "`pdf_url` (a direct, open-access PDF link) and call `web_fetch` on it, then "
    "Read the staged file — that handles figures via vision. `abstract` is for "
    "triage only: use it (plus `citations`, `venue`, `year`) to pick which 2-4 "
    "papers are worth fetching. A hit with `pdf_url: null` has no open-access PDF "
    "(paywalled or none found); `landing_url` is its publisher/abstract page. "
    "`citations` is null for sources without a citation graph (arXiv, NTRS) — a "
    "NASA/NTRS report is authoritative regardless of citation count."
)


class PaperHit(BaseModel):
    """One paper, normalized across all sources."""

    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    citations: int | None = None  # None where the source has no citation graph
    doi: str | None = None
    pdf_url: str | None = None  # DIRECT open-access PDF — feed to web_fetch
    landing_url: str | None = None  # publisher / abstract page
    abstract: str | None = None
    open_access: bool = False
    source: Literal["openalex", "arxiv", "ntrs", "semantic_scholar"]


class PaperSearchResult(BaseModel):
    """Handoff descriptor — a ranked candidate list, not extracted content."""

    status: Literal["ok", "error"]
    query: str
    sort: Literal["relevance", "citations", "recent"]
    results: list[PaperHit] = Field(default_factory=list)
    sources_queried: list[str] = Field(default_factory=list)
    sources_failed: list[str] = Field(default_factory=list)  # e.g. S2 on a 429
    usage: str = USAGE
    error: str | None = None  # set only when status == "error"
