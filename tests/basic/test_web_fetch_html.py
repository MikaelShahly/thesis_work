"""web_fetch — HTML extractor (basic, offline).

Pure-unit coverage of the logic-heavy helpers plus a few ``process()``-level
fixtures for the site shapes that can't be exercised live (CFD-Online is behind a
Cloudflare JS challenge). Image downloads are stubbed so these stay offline; the
real download path is covered by the gated production tests.
"""

from __future__ import annotations

import pytest
from lxml import html as lxml_html

from src.tools.web_fetch import html as H
from src.tools.web_fetch.fetcher import FetchOutcome
from src.tools.web_fetch.schemas import FigureRef


@pytest.fixture(autouse=True)
def _no_image_download(monkeypatch):
    async def _stub(candidates, entry):
        return []
    monkeypatch.setattr(H, "_download_figures", _stub)


async def _run(html_str: str, entry, url="https://x.com/page", force_raw=False):
    outcome = FetchOutcome("ok", url, content_type="html",
                           raw=html_str.encode("utf-8"), encoding="utf-8")
    return await H.process(outcome, entry, "2026-06-12", url, force_raw=force_raw)


# ── Doxygen code preservation (the OpenFOAM-source case) ─────────────────────
def test_extract_and_restore_code_blocks():
    # Full <html> doc: lxml unwraps a bare "<body>..." to its child as root.
    dom = lxml_html.fromstring(
        "<html><body>"
        '<div class="fragment">'
        '<div class="line"><span class="lineno">1</span>scalar p = 0;</div>'
        '<div class="line"><span class="lineno">2</span>label n = mesh.nCells();</div>'
        "</div>"
        "<pre>dict { key value; }</pre>"
        "</body></html>"
    )
    blocks = H._extract_code_blocks(dom)
    assert len(blocks) == 2  # Doxygen fragment + bare <pre>
    frag_code = next(v for v in blocks.values() if "scalar p" in v)
    assert frag_code == "scalar p = 0;\nlabel n = mesh.nCells();"  # gutter dropped, \n kept
    # restore both the bare (trafilatura) and pre-fenced (markdownify) sentinel forms
    bare = "\n\n".join(blocks)
    restored = H._restore_code_blocks(bare, blocks)
    assert "```\nscalar p = 0;\nlabel n = mesh.nCells();\n```" in restored
    assert "```\ndict { key value; }\n```" in restored
    first = next(iter(blocks))
    assert H._restore_code_blocks(f"```\n{first}\n```", blocks).count("```") == 2


@pytest.mark.asyncio
async def test_process_doxygen_source_fences_code(tmp_path):
    html_str = (
        "<html><body><h1>fvMesh.C</h1>"
        '<div class="fragment">'
        '<div class="line">Info&lt;&lt; "start" &lt;&lt; endl;</div>'
        '<div class="line">forAll(cells, i) { sum += V[i]; }</div>'
        "</div></body></html>"
    )
    r = await _run(html_str, tmp_path)
    md = (tmp_path / "content.md").read_text()
    assert "```" in md  # code fenced, not shredded into prose
    assert "forAll(cells, i)" in md


# ── forum: post bodies survive, chrome stripped ──────────────────────────────
@pytest.mark.asyncio
async def test_process_forum_keeps_posts_marks_chrome(tmp_path):
    html_str = """<html><head><title>simpleFoam BCs -- CFD Online</title></head><body>
    <nav><a href="/">Home</a><a href="/Forums/">Forums</a><a href="/search">Search</a></nav>
    <div class="post"><div class="content">
      <p>For external aero with simpleFoam I use a freestream inlet velocity boundary
      condition and zeroGradient on pressure at the inlet. The turbulence quantities
      k and omega are set with fixedValue at the inlet and inletOutlet downstream.</p>
      <pre>inlet { type fixedValue; value uniform (10 0 0); }</pre>
    </div></div>
    <footer><a href="/contact">Contact</a><a href="/privacy">Privacy</a></footer>
    </body></html>"""
    r = await _run(html_str, tmp_path, url="https://www.cfd-online.com/Forums/openfoam/1-x.html")
    md = (tmp_path / "content.md").read_text()
    assert "freestream inlet velocity" in md  # post body survived
    assert "inlet { type fixedValue" in md  # pasted dict survived
    chrome = {l.url for l in r.links if l.type == "chrome"}
    assert any("/contact" in u for u in chrome) and any(u.endswith("/Forums/") for u in chrome)
    assert r.metadata.page_kind == "forum"  # URL-pattern guess


def test_dedup_collapses_repeated_signature_lines():
    md = "post one\n" + "\n".join(["Reply With Quote"] * 5) + "\nreal content here"
    out = H._dedup_repeated_blocks(md)
    assert out.count("Reply With Quote") == 1
    assert "post one" in out and "real content here" in out


# ── data-link harvest (the TMR guarantee) ────────────────────────────────────
@pytest.mark.asyncio
async def test_process_harvests_typed_data_links(tmp_path):
    html_str = """<html><body><h1>SA results</h1>
    <p>Download the grids and results below for the flat plate verification case.</p>
    <ul>
      <li><a href="FlatPlate/SA/cf_plate.dat">cf vs x</a></li>
      <li><a href="FlatPlate/SA/cfl3d_typical.inp">input deck</a></li>
      <li><a href="grids/mesh.cgns">mesh</a></li>
      <li><a href="https://www.kbwiki.ercoftac.org/db">ERCOFTAC database</a></li>
      <li><a href="other.html">another case</a></li>
    </ul></body></html>"""
    r = await _run(html_str, tmp_path, url="https://tmbwg.github.io/turbmodels/flatplate_sa.html")
    by_url = {l.url.rsplit("/", 1)[-1]: l.type for l in r.links}
    assert by_url["cf_plate.dat"] == "data"
    assert by_url["cfl3d_typical.inp"] == "data"
    assert by_url["mesh.cgns"] == "data"
    assert by_url["db"] == "external"  # ERCOFTAC, off-domain
    assert by_url["other.html"] == "nav"
    # none dropped: every <a> with a real href is present
    assert len([l for l in r.links if l.type == "data"]) == 3


# ── pure helpers ─────────────────────────────────────────────────────────────
def test_collect_images_filters_decoration_keeps_content(tmp_path):
    dom = lxml_html.fromstring("""<body>
      <a href="#top"><img src="skip.gif" alt="skip to content"></a>
      <img src="logo.png" alt="Site Logo">
      <img src="data:image/gif;base64,R0lGOD">
      <span><img src="closed.png" alt="-"></span>
      <p><img src="velocity_profile.png" alt="velocity profile"></p>
    </body>""")
    kept = {u.rsplit("/", 1)[-1] for u, _ in H._collect_images(dom, "https://x.com/page")}
    assert kept == {"velocity_profile.png"}


def test_collect_images_skips_latex_equation_images():
    # LaTeX-alt equation images (TMR-style) are skipped — their alt IS the content,
    # kept inline as text — so the figure budget goes to real plots/sketches.
    # Descriptive- or empty-alt images are kept (the image is the only form).
    dom = lxml_html.fromstring(
        "<html><body>"
        '<p><img src="eqns/img1.png" alt="\\tau_{ij} = 2 \\mu_t S_{ij}"></p>'
        '<p><img src="eqns/img2.png" alt="c_2=0.7"></p>'
        '<p><img src="eqns/img3.png" alt="k_s"></p>'
        '<p><img src="sketch.jpg" alt="sketch demonstrating minimum distance"></p>'
        '<p><img src="cf_plot.png" alt="skin friction coefficient over the plate"></p>'
        '<p><img src="rendered_eqn.png" alt=""></p>'
        "</body></html>"
    )
    kept = {u.rsplit("/", 1)[-1] for u, _ in H._collect_images(dom, "https://x.com/p")}
    assert kept == {"sketch.jpg", "cf_plot.png", "rendered_eqn.png"}


def test_figure_gallery_appends_only_unreferenced_figures():
    figs = [
        FigureRef(id="fig-1", caption="inline plot", image_path="/abs/fig-1.png"),
        FigureRef(id="fig-2", caption="table plot", image_path="/abs/fig-2.png"),
    ]
    # fig-1 already embedded by trafilatura; fig-2 is a dropped table-cell plot.
    md = "intro\n![inline plot](/abs/fig-1.png)\nbody"
    out = H._append_figure_gallery(md, figs)
    assert "## Figures" in out
    assert out.count("/abs/fig-2.png") == 1  # the index-only figure now referenced
    assert out.count("/abs/fig-1.png") == 1  # the inline one is NOT duplicated
    # when every figure is already referenced, no gallery is added
    both = "![a](/abs/fig-1.png)\n![b](/abs/fig-2.png)"
    assert "## Figures" not in H._append_figure_gallery(both, figs)


def test_inline_figures_rewrites_to_local_abs_path():
    md = "text\n![grid](grid.png)\nmore"
    figs = [FigureRef(id="fig-1", src_url="https://x.com/grid.png", image_path="/abs/figures/fig-1.png")]
    out = H._inline_figures(md, figs, "https://x.com/page")
    assert "![grid](/abs/figures/fig-1.png)" in out


def test_line_anchored_toc_ranges():
    md = "# A\nintro\n## B\nbody\n## C\nend"
    toc = H._line_anchored_toc(md)
    assert [(e.title, e.line, e.level) for e in toc] == [("A", 1, 1), ("B", 3, 2), ("C", 5, 2)]
    assert toc[0].line_end == 2 and toc[2].line_end == 6


def test_table_refs_detects_markdown_tables():
    md = "intro\n\n| a | b |\n| - | - |\n| 1 | 2 |\n| 3 | 4 |\n\nafter"
    refs = H._table_refs(md)
    assert len(refs) == 1 and refs[0].n_rows == 2 and refs[0].n_cols == 2
