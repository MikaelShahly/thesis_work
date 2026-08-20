"""OpenAlex source — the primary index.

No key required; the optional ``mailto`` puts us in OpenAlex's faster "polite
pool". Returns ``best_oa_location.pdf_url`` (a direct OA PDF) and
``cited_by_count`` (real citation ranking). The OpenFOAM Journal lives here too,
reachable by its ISSN — ``openfoam_journal_only`` just adds that filter.
"""

from __future__ import annotations

import os

import httpx

from src.tools.paper_search.schemas import PaperHit

_ENDPOINT = "https://api.openalex.org/works"
_OPENFOAM_JOURNAL_ISSN = "2753-8168"
# Polite-pool contact (faster, recommended by OpenAlex). Override via env; the
# fallback is a no-reply, never a personal address.
_MAILTO = os.environ.get("OPENALEX_MAILTO", "agenticcfd@users.noreply.github.com")

_SORT = {
    "relevance": "relevance_score:desc",
    "citations": "cited_by_count:desc",
    "recent": "publication_date:desc",
}


def _abstract(inv: dict | None) -> str | None:
    """OpenAlex ships abstracts as an inverted index {word: [positions]}; rebuild
    the running text from it."""
    if not inv:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    text = " ".join(w for _, w in positions).strip()
    return text[:2000] or None


def _hit(work: dict) -> PaperHit | None:
    title = work.get("title") or work.get("display_name")
    if not title:
        return None
    loc = work.get("primary_location") or {}
    source = loc.get("source") or {}
    oa = work.get("best_oa_location") or {}
    doi = work.get("doi")
    if doi:
        doi = doi.removeprefix("https://doi.org/")
    return PaperHit(
        title=title,
        authors=[
            a["author"]["display_name"]
            for a in work.get("authorships", [])
            if a.get("author", {}).get("display_name")
        ][:12],
        year=work.get("publication_year"),
        venue=source.get("display_name"),
        citations=work.get("cited_by_count"),
        doi=doi,
        pdf_url=oa.get("pdf_url"),
        landing_url=loc.get("landing_page_url") or work.get("id"),
        abstract=_abstract(work.get("abstract_inverted_index")),
        open_access=bool((work.get("open_access") or {}).get("is_oa")),
        source="openalex",
    )


async def search(
    client: httpx.AsyncClient,
    query: str,
    *,
    sort: str,
    max_results: int,
    openfoam_journal_only: bool = False,
) -> list[PaperHit]:
    params = {
        "search": query,
        "per-page": min(max_results, 50),
        "sort": _SORT.get(sort, _SORT["relevance"]),
        "mailto": _MAILTO,
    }
    if openfoam_journal_only:
        params["filter"] = f"primary_location.source.issn:{_OPENFOAM_JOURNAL_ISSN}"
    resp = await client.get(_ENDPOINT, params=params)
    resp.raise_for_status()
    works = resp.json().get("results", [])
    return [h for w in works if (h := _hit(w)) is not None]
