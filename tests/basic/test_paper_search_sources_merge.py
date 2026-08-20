"""paper_search — source parsing + merge/dedup/sort (basic, offline).

Each source is exercised with an httpx.MockTransport feeding canned API payloads,
so parsing is verified without network. merge_hits and the best-effort drop are
tested directly.
"""

from __future__ import annotations

import httpx
import pytest

from src.tools.paper_search import arxiv, ntrs, openalex, semantic_scholar, tool
from src.tools.paper_search.merge import merge_hits
from src.tools.paper_search.schemas import PaperHit


def _client(body: str | dict, *, content_type="application/json") -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(body, dict):
            return httpx.Response(200, json=body)
        return httpx.Response(200, text=body, headers={"content-type": content_type})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ── OpenAlex: inverted-index abstract, OA pdf, citations, DOI strip ──────────
@pytest.mark.asyncio
async def test_openalex_parses_pdf_citations_and_abstract():
    payload = {
        "results": [
            {
                "title": "Wall functions in RANS",
                "publication_year": 2021,
                "cited_by_count": 42,
                "doi": "https://doi.org/10.1234/abc",
                "authorships": [{"author": {"display_name": "A. Researcher"}}],
                "primary_location": {
                    "source": {"display_name": "J. Fluid Mech."},
                    "landing_page_url": "https://example.com/abc",
                },
                "best_oa_location": {"pdf_url": "https://example.com/abc.pdf"},
                "open_access": {"is_oa": True},
                "abstract_inverted_index": {"Turbulent": [0], "boundary": [1], "layer": [2]},
            }
        ]
    }
    async with _client(payload) as c:
        hits = await openalex.search(c, "wall functions", sort="relevance", max_results=5)
    assert len(hits) == 1
    h = hits[0]
    assert h.pdf_url == "https://example.com/abc.pdf"
    assert h.citations == 42
    assert h.doi == "10.1234/abc"  # https://doi.org/ stripped
    assert h.abstract == "Turbulent boundary layer"  # rebuilt from inverted index
    assert h.source == "openalex"


# ── arXiv: Atom XML, pdf link, no citations ──────────────────────────────────
@pytest.mark.asyncio
async def test_arxiv_parses_atom_and_pdf_link():
    atom = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry>
        <id>http://arxiv.org/abs/2104.00001v1</id>
        <title>LES of a jet</title>
        <summary>  We simulate   a turbulent jet. </summary>
        <published>2021-04-01T00:00:00Z</published>
        <author><name>B. Author</name></author>
        <link title="pdf" href="http://arxiv.org/pdf/2104.00001v1" type="application/pdf"/>
        <arxiv:doi>10.5555/xyz</arxiv:doi>
      </entry>
    </feed>"""
    async with _client(atom, content_type="application/atom+xml") as c:
        hits = await arxiv.search(c, "jet", sort="recent", max_results=5)
    assert len(hits) == 1
    h = hits[0]
    assert h.pdf_url == "http://arxiv.org/pdf/2104.00001v1"
    assert h.year == 2021
    assert h.citations is None  # arXiv has no citation graph
    assert h.abstract == "We simulate a turbulent jet."  # whitespace collapsed


# ── NTRS: nested author/meta, relative pdf link prefixed ─────────────────────
@pytest.mark.asyncio
async def test_ntrs_parses_authors_and_prefixes_pdf():
    payload = {
        "results": [
            {
                "id": 20200002448,
                "title": "Turbulence measurements for CFD",
                "distributionDate": "2020-05-01T00:00:00.0+00:00",
                "abstract": "Junction flow data.",
                "stiTypeDetails": "Technical Report",
                "authorAffiliations": [{"meta": {"author": {"name": "C. NASA"}}}],
                "downloads": [
                    {"links": {"pdf": "/api/citations/20200002448/downloads/x.pdf"}}
                ],
            }
        ]
    }
    async with _client(payload) as c:
        hits = await ntrs.search(c, "junction", sort="relevance", max_results=5)
    assert len(hits) == 1
    h = hits[0]
    assert h.pdf_url == "https://ntrs.nasa.gov/api/citations/20200002448/downloads/x.pdf"
    assert h.authors == ["C. NASA"]
    assert h.landing_url == "https://ntrs.nasa.gov/citations/20200002448"
    assert h.year == 2020


# ── Semantic Scholar: openAccessPdf, tldr fallback, DOI from externalIds ─────
@pytest.mark.asyncio
async def test_semantic_scholar_parses_oa_and_tldr():
    payload = {
        "data": [
            {
                "title": "Detached eddy simulation",
                "year": 2019,
                "citationCount": 100,
                "venue": "AIAA J.",
                "externalIds": {"DOI": "10.9/des"},
                "openAccessPdf": {"url": "https://example.com/des.pdf"},
                "authors": [{"name": "D. Spalart"}],
                "abstract": None,
                "tldr": {"text": "A hybrid RANS-LES method."},
            }
        ]
    }
    async with _client(payload) as c:
        hits = await semantic_scholar.search(c, "des", sort="citations", max_results=5)
    h = hits[0]
    assert h.pdf_url == "https://example.com/des.pdf"
    assert h.doi == "10.9/des"
    assert h.abstract == "A hybrid RANS-LES method."  # tldr used when abstract null


# ── merge: dedup by DOI, gap-fill, citation sort ─────────────────────────────
def test_merge_dedups_by_doi_and_fills_gaps_then_sorts():
    oa = PaperHit(title="X", doi="10.1/x", citations=5, pdf_url=None, source="openalex")
    s2 = PaperHit(title="X dup", doi="10.1/x", citations=5,
                  pdf_url="https://e/x.pdf", source="semantic_scholar")
    ar = PaperHit(title="Y", doi=None, citations=None,
                  pdf_url="https://e/y.pdf", source="arxiv")
    merged = merge_hits(
        {"openalex": [oa], "semantic_scholar": [s2], "arxiv": [ar]},
        sort="citations", limit=10,
    )
    # X and its S2 duplicate collapse to one entry that gained the S2 pdf_url.
    assert len(merged) == 2
    x = next(h for h in merged if h.doi == "10.1/x")
    assert x.pdf_url == "https://e/x.pdf"  # absorbed from the duplicate
    # citation sort: X (5 cites) before Y (None).
    assert merged[0].doi == "10.1/x"


# ── best-effort: a raising source is dropped, search still ok ────────────────
@pytest.mark.asyncio
async def test_best_effort_drops_failed_source(monkeypatch):
    async def good(client, query, *, sort, max_results, openfoam_journal_only=False):
        return [PaperHit(title="ok", source="openalex")]

    async def boom(client, query, *, sort, max_results, openfoam_journal_only=False):
        raise httpx.HTTPStatusError("429", request=None, response=None)

    monkeypatch.setitem(tool._SOURCES, "openalex", good)
    monkeypatch.setitem(tool._SOURCES, "semantic_scholar", boom)
    monkeypatch.setitem(tool._SOURCES, "arxiv", boom)
    monkeypatch.setitem(tool._SOURCES, "ntrs", boom)

    res = await tool.run_search({"query": "turbulence"})
    assert res.status == "ok"
    assert res.sources_queried == ["openalex"]
    assert set(res.sources_failed) == {"semantic_scholar", "arxiv", "ntrs"}
    assert len(res.results) == 1


@pytest.mark.asyncio
async def test_empty_query_is_error():
    res = await tool.run_search({"query": "  "})
    assert res.status == "error"
