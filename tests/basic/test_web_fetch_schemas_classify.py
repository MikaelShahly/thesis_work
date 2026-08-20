"""web_fetch — schema round-trip + link classification (basic, no network)."""

from __future__ import annotations

from src.tools.web_fetch.classify import classify_link
from src.tools.web_fetch.schemas import USAGE, DocMetadata, FetchResult, Link


def test_fetchresult_json_roundtrip_carries_usage_and_defaults():
    r = FetchResult(
        status="ok",
        content_type="html",
        content_path="/abs/content.md",
        metadata=DocMetadata(source_url="https://x/y"),
        links=[Link(url="https://x/g.dat", type="data", mime_hint="dat")],
    )
    again = FetchResult.model_validate_json(r.model_dump_json())
    assert again.status == "ok"
    assert again.usage == USAGE  # fixed access contract always present
    assert again.links[0].type == "data" and again.links[0].mime_hint == "dat"
    assert again.toc == [] and again.figures == []  # empty defaults survive


def test_dropped_schemes_return_none():
    for u in (
        "mailto:a@b.com",
        "tel:+1",
        "javascript:void(0)",
        "data:image/png;base64,xxxx",
        "#section",
        "#",
    ):
        assert classify_link(u, base_host="x.com") is None


def test_chrome_wins_over_everything_but_drop():
    # In a nav/header/footer/aside region → chrome, even a data extension.
    assert classify_link("https://x.com/grid.dat", in_chrome=True, base_host="x.com") == (
        "chrome",
        None,
    )


def test_data_extensions_typed_with_mime_hint():
    for ext in ("dat", "csv", "vtk", "stl", "msh", "cgns", "nml", "inp", "p3d", "h5"):
        t, hint = classify_link(f"https://x.com/file.{ext}", base_host="x.com")
        assert t == "data" and hint == ext


def test_extension_checked_before_host():
    # Same-site .dat must type as data, NOT nav (extension before host).
    assert classify_link("https://x.com/sub/grid.dat", base_host="x.com")[0] == "data"


def test_pdf_is_alternate_pdf():
    assert classify_link("https://x.com/paper.pdf", base_host="x.com") == (
        "alternate_pdf",
        "pdf",
    )


def test_citation_detection():
    assert classify_link("https://doi.org/10.1063/1.12345", base_host="x.com")[0] == "citation"
    assert classify_link("https://arxiv.org/abs/2401.00001", base_host="x.com")[0] == "citation"
    assert classify_link("https://x.com/doi/10.2514/1.J012345", base_host="x.com")[0] == "citation"


def test_nav_vs_external_by_registrable_domain():
    # same registrable domain (subdomain differs) → nav (internal trail)
    assert classify_link(
        "https://turbmodels.larc.nasa.gov/x.html", base_host="larc.nasa.gov"
    )[0] == "nav"
    # different registrable domain → external (valuable: ERCOFTAC, JAXA, …)
    assert classify_link(
        "https://www.kbwiki.ercoftac.org/w", base_host="tmbwg.github.io"
    )[0] == "external"
