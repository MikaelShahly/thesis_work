"""Semantic Scholar source — best-effort third ranker.

Adds TLDRs and a rich citation graph. The keyless tier is heavily rate-limited
(shared pool → frequent 429s), so this is treated as best-effort: any error,
including a 429, propagates and the orchestrator drops this source from the
merge rather than failing the whole search. Set ``SEMANTIC_SCHOLAR_API_KEY`` in
the env to lift the rate limit. The search endpoint has no server-side sort, so
``citations``/``recent`` ordering is handled globally by the merge layer.
"""

from __future__ import annotations

import os

import httpx

from src.tools.paper_search.schemas import PaperHit

_ENDPOINT = "https://api.semanticscholar.org/graph/v1/paper/search"
_FIELDS = "title,year,abstract,citationCount,openAccessPdf,externalIds,venue,authors,tldr"


def _hit(p: dict) -> PaperHit | None:
    title = (p.get("title") or "").strip()
    if not title:
        return None
    oa = p.get("openAccessPdf") or {}
    tldr = (p.get("tldr") or {}).get("text")
    return PaperHit(
        title=title,
        authors=[a["name"] for a in p.get("authors", []) if a.get("name")][:12],
        year=p.get("year"),
        venue=p.get("venue") or None,
        citations=p.get("citationCount"),
        doi=(p.get("externalIds") or {}).get("DOI"),
        pdf_url=oa.get("url"),
        landing_url=p.get("url"),
        abstract=(p.get("abstract") or tldr or "").strip()[:2000] or None,
        open_access=bool(oa.get("url")),
        source="semantic_scholar",
    )


async def search(
    client: httpx.AsyncClient,
    query: str,
    *,
    sort: str,
    max_results: int,
    openfoam_journal_only: bool = False,
) -> list[PaperHit]:
    headers = {}
    key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if key:
        headers["x-api-key"] = key
    params = {"query": query, "limit": min(max_results, 100), "fields": _FIELDS}
    resp = await client.get(_ENDPOINT, params=params, headers=headers)
    resp.raise_for_status()  # 429 propagates → orchestrator drops this source
    data = resp.json().get("data", [])
    return [h for p in data if (h := _hit(p)) is not None]
