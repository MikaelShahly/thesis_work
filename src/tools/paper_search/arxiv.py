"""arXiv source — preprints (strong for ``physics.flu-dyn``).

No key. The API returns Atom XML. arXiv has no citation graph, so ``citations``
is always None and a ``citations`` sort falls back to relevance.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from src.tools.paper_search.schemas import PaperHit

_ENDPOINT = "https://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"

_SORT = {
    "relevance": ("relevance", "descending"),
    "recent": ("submittedDate", "descending"),
    "citations": ("relevance", "descending"),  # no citation data → relevance
}


def _hit(entry: ET.Element) -> PaperHit | None:
    title = (entry.findtext(f"{_ATOM}title") or "").strip()
    if not title:
        return None
    abs_id = (entry.findtext(f"{_ATOM}id") or "").strip()

    pdf_url = None
    for link in entry.findall(f"{_ATOM}link"):
        if link.get("title") == "pdf" or link.get("type") == "application/pdf":
            pdf_url = link.get("href")
            break
    if not pdf_url and "/abs/" in abs_id:
        pdf_url = abs_id.replace("/abs/", "/pdf/")

    published = entry.findtext(f"{_ATOM}published") or ""
    year = int(published[:4]) if published[:4].isdigit() else None
    doi = (entry.findtext(f"{_ARXIV}doi") or "").strip() or None
    summary = (entry.findtext(f"{_ATOM}summary") or "").strip()

    return PaperHit(
        title=" ".join(title.split()),
        authors=[
            (a.findtext(f"{_ATOM}name") or "").strip()
            for a in entry.findall(f"{_ATOM}author")
        ][:12],
        year=year,
        venue="arXiv",
        citations=None,
        doi=doi,
        pdf_url=pdf_url,
        landing_url=abs_id or None,
        abstract=" ".join(summary.split())[:2000] or None,
        open_access=True,
        source="arxiv",
    )


async def search(
    client: httpx.AsyncClient,
    query: str,
    *,
    sort: str,
    max_results: int,
    openfoam_journal_only: bool = False,
) -> list[PaperHit]:
    sort_by, sort_order = _SORT.get(sort, _SORT["relevance"])
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": sort_by,
        "sortOrder": sort_order,
    }
    resp = await client.get(_ENDPOINT, params=params)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    return [
        h
        for e in root.findall(f"{_ATOM}entry")
        if (h := _hit(e)) is not None
    ]
