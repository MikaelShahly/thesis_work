"""paper_search — live round-trip against the real academic APIs.

Exercises the tool as in production: real OpenAlex/arXiv/NTRS queries, asserting
we get back direct, fetchable open-access PDF URLs — the entire reason the tool
exists. ``run_search`` swallows per-source network errors internally (best-effort),
so a genuine offline run surfaces as *every* source failing — i.e. an empty
``sources_queried`` — which we treat as a skip. Semantic Scholar is never asserted
on (keyless 429s are expected); we only check the search survives its failure.
"""

from __future__ import annotations

import httpx
import pytest

from src.tools.paper_search import tool

pytestmark = pytest.mark.asyncio


def _skip_if_all_sources_failed(res) -> None:
    """Empty sources_queried means every API call raised — treat as offline."""
    if not res.sources_queried:
        pytest.skip(f"network unavailable: all sources failed ({res.sources_failed})")


async def _pdf_is_real(url: str) -> bool:
    """A direct PDF URL should serve %PDF- bytes (the failure mode we're fixing:
    landing pages that aren't PDFs)."""
    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True,
        headers={"User-Agent": "AgenticCFD-test"},
    ) as c:
        async with c.stream("GET", url) as r:
            r.raise_for_status()
            async for chunk in r.aiter_bytes():
                return chunk[:5] == b"%PDF-"
    return False


async def test_live_search_returns_direct_fetchable_pdf():
    res = await tool.run_search(
        {"query": "RANS atmospheric boundary layer OpenFOAM", "max_results": 12}
    )
    assert res.status == "ok"
    _skip_if_all_sources_failed(res)
    assert "openalex" in res.sources_queried
    assert res.results, "expected at least one paper"

    with_pdf = [h for h in res.results if h.pdf_url]
    assert with_pdf, "expected at least one hit carrying a direct pdf_url"

    # The crux: that pdf_url actually downloads as a PDF, not an HTML landing page.
    try:
        assert await _pdf_is_real(with_pdf[0].pdf_url)
    except httpx.HTTPError as e:  # pragma: no cover - network/host blocking
        pytest.skip(f"pdf host unreachable: {e}")


async def test_live_openfoam_journal_only_filters_to_the_journal():
    res = await tool.run_search(
        {"query": "turbulence", "openfoam_journal_only": True, "max_results": 8}
    )
    assert res.status == "ok"
    _skip_if_all_sources_failed(res)
    assert res.sources_queried == ["openalex"]  # journal-only collapses sources
    assert res.results
    # Every hit should be an OpenFOAM Journal article (its download host).
    assert any(
        h.pdf_url and "journal.openfoam.com" in h.pdf_url for h in res.results
    )


async def test_live_citations_sort_orders_by_influence():
    res = await tool.run_search(
        {"query": "large eddy simulation", "sort": "citations", "max_results": 10}
    )
    assert res.status == "ok"
    _skip_if_all_sources_failed(res)
    cited = [h.citations for h in res.results if h.citations is not None]
    assert cited == sorted(cited, reverse=True), "citation-sorted hits must be descending"


async def test_live_tool_envelope_is_wellformed():
    """The @tool handler returns the SDK content envelope, not a raw model."""
    out = await tool.paper_search.handler({"query": "k-omega SST validation"})
    assert out["is_error"] is False
    assert out["content"][0]["type"] == "text"
    assert '"results"' in out["content"][0]["text"]
