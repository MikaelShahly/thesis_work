"""NASA NTRS source — the CFD/aerospace technical-report repository.

No key. Canonical turbulence-model, validation, and verification-workshop
reports that the general indexes don't carry, all as public-domain PDFs. No
citation graph and no DOIs, so ``citations``/``doi`` are None; the merge layer
handles ``recent``/``citations`` sorting globally, so we just take NTRS's native
relevance order.
"""

from __future__ import annotations

import httpx

from src.tools.paper_search.schemas import PaperHit

_ENDPOINT = "https://ntrs.nasa.gov/api/citations/search"
_BASE = "https://ntrs.nasa.gov"


def _pdf_url(downloads: list) -> str | None:
    for dl in downloads or []:
        link = (dl.get("links") or {}).get("pdf")
        if link:
            return link if link.startswith("http") else _BASE + link
    return None


def _hit(r: dict) -> PaperHit | None:
    title = (r.get("title") or "").strip()
    if not title:
        return None
    date = r.get("distributionDate") or r.get("submittedDate") or ""
    year = int(date[:4]) if date[:4].isdigit() else None
    rid = r.get("id")
    return PaperHit(
        title=title,
        authors=[
            ((a.get("meta") or {}).get("author") or {}).get("name", "").strip()
            for a in r.get("authorAffiliations", [])
            if ((a.get("meta") or {}).get("author") or {}).get("name")
        ][:12],
        year=year,
        venue=r.get("stiTypeDetails") or "NASA Technical Reports Server",
        citations=None,
        doi=None,
        pdf_url=_pdf_url(r.get("downloads")),
        landing_url=f"{_BASE}/citations/{rid}" if rid else None,
        abstract=(r.get("abstract") or "").strip()[:2000] or None,
        open_access=True,
        source="ntrs",
    )


async def search(
    client: httpx.AsyncClient,
    query: str,
    *,
    sort: str,
    max_results: int,
    openfoam_journal_only: bool = False,
) -> list[PaperHit]:
    params = {"q": query, "page.size": max_results}
    resp = await client.get(_ENDPOINT, params=params)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return [h for r in results if (h := _hit(r)) is not None]
