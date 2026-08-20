"""The ``paper_search`` tool: fan out to academic indexes, merge, hand back
candidates the agent can fetch.

Static (no per-project binding): the handler queries the selected sources
concurrently, never raises (every source failure becomes a ``sources_failed``
entry — best-effort, so a rate-limited Semantic Scholar can't sink the search),
merges, and returns a ranked ``PaperSearchResult``. The agent then pipes a
chosen ``pdf_url`` into ``web_fetch`` → ``Read``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from claude_agent_sdk import tool

from src.tools.paper_search import arxiv, ntrs, openalex, semantic_scholar
from src.tools.paper_search.merge import merge_hits
from src.tools.paper_search.schemas import PaperSearchResult
from src.tools.web_fetch.fetcher import USER_AGENT

_SOURCES = {
    "openalex": openalex.search,
    "arxiv": arxiv.search,
    "ntrs": ntrs.search,
    "semantic_scholar": semantic_scholar.search,
}
_SORTS = ("relevance", "citations", "recent")
_TIMEOUT_S = 25.0

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "Keyword search: terms are AND-combined with no synonym expansion, "
                "so each word narrows results to exact lexical matches."
            ),
        },
        "sort": {
            "type": "string",
            "enum": list(_SORTS),
            "description": (
                "relevance (default); citations → seminal/canonical work "
                "(OpenAlex/S2 only); recent → latest by date."
            ),
        },
        "openfoam_journal_only": {
            "type": "boolean",
            "description": "Restrict to the OpenFOAM Journal (via OpenAlex ISSN filter).",
        },
        "sources": {
            "type": "array",
            "items": {"type": "string", "enum": list(_SOURCES)},
            "description": "Subset of sources to query; default all four.",
        },
        "max_results": {
            "type": "integer",
            "description": "Max merged results to return (default 12).",
        },
    },
    "required": ["query"],
}

_DESCRIPTION = (
    "Search the academic literature (OpenAlex, arXiv, NASA NTRS, Semantic "
    "Scholar) and get back candidates that carry a DIRECT, fetchable "
    "open-access `pdf_url`. This is the academic counterpart to web_search: use "
    "it when you want papers — not web pages — and when you intend to actually "
    "read the PDF.\n\n"
    "It does NOT return content. It returns a ranked list of hits (title, "
    "authors, year, venue, citations, abstract, pdf_url). To read a paper, take "
    "its `pdf_url` and call `web_fetch` on it, then Read the staged file — that "
    "is how you get the full text and figures. `abstract` is for triage only: "
    "decide from it which 2-4 papers are worth fetching. A hit with "
    "`pdf_url: null` has no open-access PDF (paywalled); you cannot fetch it.\n\n"
    "WHEN TO USE — prefer this over web_search for anything paper-shaped: finding "
    "reference cases, validation data, turbulence-model details, numerical "
    "methods, or prior CFD studies. web_search gives publisher landing pages that "
    "web_fetch often can't pierce; this gives direct OA PDF links that it can. "
    "Pass `openfoam_journal_only=true` for OpenFOAM Journal articles; `sort="
    "'citations'` for the seminal paper on a topic; `sort='recent'` for the "
    "latest work. NASA NTRS contributes canonical CFD/turbulence/validation "
    "reports with no citation count — judge those on authority, not citations."
)


async def run_search(args: dict[str, Any]) -> PaperSearchResult:
    a = args or {}
    query = str(a.get("query", "")).strip()
    sort = a.get("sort") if a.get("sort") in _SORTS else "relevance"
    openfoam_only = bool(a.get("openfoam_journal_only", False))
    try:
        max_results = int(a.get("max_results", 12))
    except (TypeError, ValueError):
        max_results = 12
    max_results = max(1, min(max_results, 30))

    if not query:
        return PaperSearchResult(
            status="error", query="", sort=sort, error="Empty query."
        )

    # OpenFOAM-Journal-only lives only in OpenAlex (the other indexes don't carry
    # it), so collapse the source set in that mode.
    if openfoam_only:
        names = ["openalex"]
    else:
        names = [s for s in (a.get("sources") or list(_SOURCES)) if s in _SOURCES]
        if not names:
            names = list(_SOURCES)

    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    async with httpx.AsyncClient(
        headers=headers, timeout=_TIMEOUT_S, follow_redirects=True
    ) as client:
        results = await asyncio.gather(
            *(
                _SOURCES[name](
                    client,
                    query,
                    sort=sort,
                    max_results=max_results,
                    openfoam_journal_only=openfoam_only,
                )
                for name in names
            ),
            return_exceptions=True,
        )

    by_source: dict[str, list] = {}
    failed: list[str] = []
    for name, res in zip(names, results):
        if isinstance(res, Exception):
            failed.append(name)
        else:
            by_source[name] = res

    merged = merge_hits(by_source, sort, max_results)
    return PaperSearchResult(
        status="ok",
        query=query,
        sort=sort,
        results=merged,
        sources_queried=list(by_source.keys()),
        sources_failed=failed,
    )


@tool("paper_search", _DESCRIPTION, _INPUT_SCHEMA)
async def paper_search(args: dict[str, Any]) -> dict[str, Any]:
    result = await run_search(args)
    return {
        "content": [
            {"type": "text", "text": result.model_dump_json(exclude_none=True)}
        ],
        "is_error": result.status == "error",
    }
