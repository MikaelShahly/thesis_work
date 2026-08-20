"""Merge layer: dedup → interleave → global sort.

Per-source relevance scores aren't comparable across APIs, so we never merge by
score. Instead we round-robin interleave (each source's own rank preserved, top
hits float up), dedup by DOI (fallback: normalized title) keeping the richest
copy, then apply the one global sort the agent asked for. Relevance keeps the
interleave order.
"""

from __future__ import annotations

import re

from src.tools.paper_search.schemas import PaperHit

# Interleave priority — OpenAlex leads (best metadata + OA links), arXiv last.
SOURCE_ORDER = ["openalex", "semantic_scholar", "ntrs", "arxiv"]


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def _key(h: PaperHit) -> str:
    if h.doi:
        return "doi:" + h.doi.lower()
    return "title:" + _norm_title(h.title)


def _absorb(keep: PaperHit, dup: PaperHit) -> None:
    """Fill gaps in the kept hit from a duplicate from another source."""
    if not keep.pdf_url and dup.pdf_url:
        keep.pdf_url = dup.pdf_url
    if keep.citations is None and dup.citations is not None:
        keep.citations = dup.citations
    if not keep.abstract and dup.abstract:
        keep.abstract = dup.abstract
    if not keep.doi and dup.doi:
        keep.doi = dup.doi
    keep.open_access = keep.open_access or dup.open_access


def merge_hits(
    by_source: dict[str, list[PaperHit]], sort: str, limit: int
) -> list[PaperHit]:
    lists = [by_source[s] for s in SOURCE_ORDER if by_source.get(s)]
    seen: dict[str, PaperHit] = {}
    order: list[PaperHit] = []

    depth = max((len(lst) for lst in lists), default=0)
    for i in range(depth):
        for lst in lists:
            if i >= len(lst):
                continue
            h = lst[i]
            k = _key(h)
            if k in seen:
                _absorb(seen[k], h)
                continue
            seen[k] = h
            order.append(h)

    if sort == "citations":
        order.sort(key=lambda h: (h.citations is None, -(h.citations or 0)))
    elif sort == "recent":
        order.sort(key=lambda h: (h.year is None, -(h.year or 0)))

    return order[:limit]
