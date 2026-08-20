"""End-to-end dispatch round-trip for the quick_viz tool.

Builds the project-bound tool via ``make_quick_viz`` and invokes its
handler with a real YAML config against the sample OpenFOAM case, then
asserts the renderer actually wrote a PNG + ``.pvsm`` and returned the
expected JSON. This exercises the real subprocess path — including the
build-specific quirk that pvbatch exits NONZERO on a benign teardown
crash, so success is decided by the stdout JSON, not the exit code.

Skipped when pvbatch (or ``QUICKVIZ_PVBATCH``) isn't on PATH or the
sample case is missing.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

import pytest

_CASE = Path(__file__).resolve().parents[2] / "tests" / "openFoam_test_case"
_PVBATCH = os.environ.get("QUICKVIZ_PVBATCH", "pvbatch")

pytestmark = [
    pytest.mark.skipif(
        shutil.which(_PVBATCH) is None,
        reason=f"{_PVBATCH!r} not on PATH (set QUICKVIZ_PVBATCH)",
    ),
    pytest.mark.skipif(
        not (_CASE / "constant" / "polyMesh" / "boundary").is_file(),
        reason="sample OpenFOAM case missing",
    ),
]


def test_quick_viz_renders_boundary_overview(tmp_path):
    from src.tools.quick_viz import make_quick_viz

    out_png = tmp_path / "overview.png"
    # `case: .` resolves against pvbatch's cwd, which make_quick_viz binds
    # to the project dir (here the case dir) — the same path-resolution the
    # agent relies on in production.
    cfg = (
        "case: .\n"
        f"output: {out_png}\n"
        "time: 0\n"
        "legend: true\n"
        "boundaries: [{patch: walls}, {patch: inlet}, {patch: outlet}]\n"
        "view: {preset: iso}\n"
    )
    res = asyncio.run(make_quick_viz(_CASE).handler({"config": cfg}))

    assert not res.get("is_error"), res["content"][0]["text"]
    payload = json.loads(res["content"][0]["text"])
    assert Path(payload["output"]).is_file()
    assert Path(payload["state"]).is_file()
    assert out_png.stat().st_size > 0


def test_quick_viz_unknown_field_is_error(tmp_path):
    # render.py raises on an unknown color_by field; with no JSON on stdout
    # the tool must report is_error (this is the stdout-parse / exit-code
    # path that the teardown crash would otherwise mask). `output:` is set
    # so validation passes and we actually reach the field lookup.
    from src.tools.quick_viz import make_quick_viz

    cfg = (
        "case: .\n"
        f"output: {tmp_path / 'x.png'}\n"
        "time: 0\n"
        "boundaries:\n"
        "  color_by: {field: __no_such_field__}\n"
        "  patches: [{patch: walls}]\n"
    )
    res = asyncio.run(make_quick_viz(_CASE).handler({"config": cfg}))
    assert res.get("is_error") is True


def test_quick_viz_missing_output_is_error():
    # output: is required — a config without it must fail validation, not
    # silently render to a default path.
    from src.tools.quick_viz import make_quick_viz

    cfg = "case: .\ntime: 0\nboundaries: [{patch: walls}]\n"
    res = asyncio.run(make_quick_viz(_CASE).handler({"config": cfg}))
    assert res.get("is_error") is True
    assert "output" in res["content"][0]["text"].lower()
