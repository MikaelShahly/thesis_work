"""web_fetch — live production round-trips (opt-in).

Real network fetches of the target corpus. Gated behind ``RUN_LIVE_WEBFETCH_TESTS``
(mirrors ``RUN_LIVE_SUBAGENT_TESTS``) so the default suite stays offline/fast.

    RUN_LIVE_WEBFETCH_TESTS=1 uv run pytest tests/production/test_web_fetch_roundtrip.py

Validates the acceptance criteria against live sites: data links never lost +
typed, figures Read-able by absolute path, code preserved verbatim, cache serves
without a second network call, and the full make_web_fetch → handler dispatch
returns a valid FetchResult envelope.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.tools.web_fetch.cache import cache_key
from src.tools.web_fetch.schemas import FetchResult
from src.tools.web_fetch.tool import make_web_fetch, run_pipeline

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("RUN_LIVE_WEBFETCH_TESTS"),
        reason="Live network test. Set RUN_LIVE_WEBFETCH_TESTS=1 to enable.",
    ),
    pytest.mark.asyncio,
]

TMR_DATA = "https://tmbwg.github.io/turbmodels/flatplate_sa.html"
OPENFOAM_DOC = (
    "https://doc.openfoam.com/2312/tools/pre-processing/mesh/generation/snappyhexmesh/#"
)
WIKIPEDIA = "https://en.wikipedia.org/wiki/Turbulence_modeling"


async def test_tmr_data_links_typed_and_figures_readable(tmp_path):
    r = await run_pipeline({"url": TMR_DATA}, tmp_path / ".webcache")
    assert r.status == "ok" and r.content_type == "html"
    data = [l for l in r.links if l.type == "data"]
    assert len(data) >= 10, "TMR SA page should surface many data files"
    exts = {l.url.rsplit(".", 1)[-1].split("?")[0] for l in data}
    assert {"dat", "inp"} & exts, f"expected .dat/.inp among data links, got {exts}"
    assert Path(r.content_path).is_file()
    # figures downloaded → absolute, Read-able paths
    assert r.figures, "result plots should download"
    for f in r.figures:
        assert os.path.isabs(f.image_path) and Path(f.image_path).is_file()


async def test_openfoam_doc_extracts_content_code_and_toc(tmp_path):
    r = await run_pipeline({"url": OPENFOAM_DOC}, tmp_path / ".webcache")
    assert r.status == "ok" and r.content_type == "html"
    md = Path(r.content_path).read_text()
    assert "snappyHexMesh" in md
    assert "```" in md, "doc code blocks (e.g. the Usage listing) must be fenced"
    titles = {e.title for e in r.toc}
    assert {"Overview", "Configuration"} <= titles, f"section TOC missing: {titles}"


async def test_wikipedia_not_blocked_by_robots(tmp_path):
    # Regression for the UA fix: our product token must not contain a robots
    # bot-name substring ("fetch") that Wikipedia's `User-agent: Fetch` matches.
    r = await run_pipeline({"url": WIKIPEDIA}, tmp_path / ".webcache")
    assert r.status == "ok", f"expected ok, got {r.status} ({r.error})"
    assert "turbulence" in Path(r.content_path).read_text().lower()


async def test_cache_serves_without_second_network_call(tmp_path):
    cache = tmp_path / ".webcache"
    r1 = await run_pipeline({"url": TMR_DATA}, cache)
    meta = cache / cache_key(TMR_DATA) / "meta.json"
    m1 = meta.stat().st_mtime_ns
    r2 = await run_pipeline({"url": TMR_DATA}, cache)
    assert r2.content_path == r1.content_path
    assert meta.stat().st_mtime_ns == m1, "cache hit must not re-write meta.json"


async def test_make_web_fetch_handler_returns_valid_envelope(tmp_path):
    tool_obj = make_web_fetch(tmp_path / ".webcache")
    out = await tool_obj.handler({"url": TMR_DATA})
    assert set(out) >= {"content", "is_error"} and out["is_error"] is False
    payload = json.loads(out["content"][0]["text"])
    parsed = FetchResult.model_validate(payload)  # envelope text is a valid FetchResult
    assert parsed.status == "ok" and parsed.content_path
