"""Live-ParaView round-trip for the bridge tools.

Spawns a real ParaView via the lifecycle manager into a fake project
directory that mirrors the agenticCFD layout (Case/ holds the
OpenFOAM tree), then exercises the phase-2 workflow end-to-end:

1. Launch ParaView empty (phase 2.1 — toolbar button click).
2. Load a `.foam` via the bridge tool with a *project-relative*
   path (phase 2.2 — right-click "Load into ParaView").
3. Capture a screenshot to a project-relative path and verify the
   file lands inside the project tree, not in `src/paraview/`.

A failure here points at the bridge / lifecycle / `PV_PROJECT_ROOT`
chain, not the agent.

Skipped automatically when ParaView is not reachable on PATH (no
binary, no display, etc.). Set `PARAVIEW_EXECUTABLE` to point at a
non-default install.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

import pytest
import pytest_asyncio

from src.paraview import lifecycle
from src.tools.paraview.change_paraview_state import (
    extract_block,
    highlight_problem_cells,
    load_dataset,
    set_camera,
    set_openfoam_patches,
    set_read_zero_time,
)
from src.tools.paraview.exec_tool import paraview_exec
from src.tools.paraview.read_paraview_state import (
    get_pipeline,
    get_source_info,
    integrate_variables,
    ping,
    probe_point,
    save_screenshot,
)


# Defacto default sample case for production tests — see
# tests/openFoam_test_case/README.md. The case has populated 0/ fields
# (U, p, k, omega, …) so coverage isn't limited to mesh-only checks.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_CASE = (
    _REPO_ROOT / "tests" / "openFoam_test_case" / "difficult_w_fields.foam"
)


def _paraview_available() -> bool:
    """Best-effort detection: binary on PATH or PARAVIEW_EXECUTABLE set."""
    exe = os.environ.get("PARAVIEW_EXECUTABLE")
    if exe and Path(exe).exists():
        return True
    return shutil.which("paraview") is not None


pytestmark = [
    pytest.mark.paraview,
    pytest.mark.skipif(
        not _paraview_available(),
        reason=(
            "ParaView not on PATH and PARAVIEW_EXECUTABLE not set; "
            "skipping live-bridge round-trip."
        ),
    ),
    pytest.mark.skipif(
        not _SAMPLE_CASE.is_file(),
        reason=f"sample case missing at {_SAMPLE_CASE}",
    ),
]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def live_bridge(tmp_path_factory):
    """Launch ParaView at a fake agenticCFD project, case preloaded.

    Builds a project layout that matches the real on-disk shape
    (`<project>/Case/case.foam` plus the OpenFOAM subtree), launches
    ParaView empty (phase 2.1 path), then drives `load_dataset` with
    a *relative* path (phase 2.2 path). If `PV_PROJECT_ROOT`
    plumbing breaks, the relative load fails here and every test in
    the module errors out — which is exactly the visibility we want.

    Module-scoped (`loop_scope="module"`): one ParaView launch per
    test run instead of per-test, and `force_kill` is the only thing
    that reliably reaps the wrapped `paraview-real` process.

    Yields the project directory so individual tests can compute
    expected file destinations.
    """
    lifecycle._reset_for_tests()
    project_dir = tmp_path_factory.mktemp("paraview-prod-project")
    case_root = project_dir / "Case"
    # Mirror the sample case's full tree into the fake project's Case/
    # subfolder. ParaView's `.foam` file is just a marker — it needs
    # the surrounding constant/, system/, and time-step dirs.
    shutil.copytree(_SAMPLE_CASE.parent, case_root)

    try:
        await lifecycle.launch(
            project_dir=project_dir,
            project_id="prod-test",
            project_name="paraview-roundtrip",
            foam_file=None,  # phase 2.1: launch empty
        )
        # phase 2.2: relative load — exercises PV_PROJECT_ROOT.
        load_result = await load_dataset.handler({"path": f"Case/{_SAMPLE_CASE.name}"})
        assert not load_result.get("is_error"), load_result["content"][0]["text"]
        yield project_dir
    finally:
        rec = lifecycle._record  # noqa: SLF001 — test-only access
        if rec is not None and rec.is_alive():
            rec.force_kill(timeout=10.0)
        lifecycle._reset_for_tests()


def _decode_tool_result(result: dict) -> dict:
    """Tools return `{content: [{type: text, text: <json str>}], ...}`.

    Pull out the first text payload and parse it. If the tool returned
    `is_error: True`, surface that — production tests fail loudly.
    """
    assert not result.get("is_error"), result["content"][0]["text"]
    text = result["content"][0]["text"]
    return json.loads(text)


@pytest.mark.asyncio
async def test_ping_responds_with_project_root(live_bridge):
    # Bridge's POST /ping does a GUI-thread roundtrip AND reports the
    # project root. The agent uses this to discover where its relative
    # paths will anchor; if the bridge ever loses that field, the
    # agent's prompt is wrong about how `ping` advertises itself.
    project_dir = live_bridge
    out = _decode_tool_result(await ping.handler({}))
    assert out.get("ok") is True
    assert Path(out["project_root"]).resolve() == project_dir.resolve()


@pytest.mark.asyncio
async def test_pipeline_contains_loaded_case(live_bridge):
    out = _decode_tool_result(await get_pipeline.handler({}))
    # PV_CASE_PATH was honoured at startup; the OpenFOAM reader should
    # be sitting in the pipeline.
    assert isinstance(out, list) and out, "pipeline empty after auto-load"
    types = [entry.get("type") for entry in out]
    assert any("FOAM" in (t or "").upper() for t in types), (
        f"no OpenFOAM reader in pipeline; types were {types}"
    )


@pytest.mark.asyncio
async def test_paraview_exec_returns_active_source_class(live_bridge):
    out = _decode_tool_result(await paraview_exec.handler(
        {"code": "result = GetActiveSource().GetClassName()"}
    ))
    # `result` is repr() of the value the script set; for a non-empty
    # class name that's a quoted Python string.
    result = out.get("result")
    assert result, f"exec returned empty result: {out}"
    assert isinstance(result, str) and len(result) > 2


@pytest.mark.asyncio
async def test_save_screenshot_relative_lands_inside_project_root(live_bridge):
    """The whole point of `PV_PROJECT_ROOT`.

    Before adapting bridge.py the relative path would have anchored on
    `src/paraview/`, leaking screenshots into the source tree. With
    the env var set by lifecycle and honoured by the bridge, this
    file MUST land inside the project directory the fixture created.
    """
    project_dir = live_bridge  # fixture yields the project root
    rel_path = "Reports/test_shot.png"
    out = _decode_tool_result(await save_screenshot.handler({"out_path": rel_path}))

    expected = (project_dir / rel_path).resolve()
    actual = Path(out["path"]).resolve()
    assert actual == expected, f"screenshot resolved to {actual}, expected {expected}"
    assert expected.is_file(), f"no file written at {expected}"


def _cam_distance(cam: dict) -> float:
    """Distance from camera to its focal point — proxy for how 'zoomed in'
    a fit is. Framing one small patch must sit closer than framing all."""
    p, f = cam["position"], cam["focal"]
    return sum((p[i] - f[i]) ** 2 for i in range(3)) ** 0.5


@pytest.mark.asyncio
async def test_set_camera_patch_frames_single_patch(live_bridge):
    """`set_camera({patch})` zooms onto one OpenFOAM block, not the whole case.

    The sample case's `inlet` is a tiny planar end-cap relative to the full
    domain, so framing it must (a) move the focal point off the whole-domain
    centre and (b) bring the camera closer than framing everything. The patch
    must be loaded first — framing reads the loaded block's bounds.
    """
    enabled = _decode_tool_result(
        await set_openfoam_patches.handler({"enable": ["patch/inlet"]})
    )
    assert "patch/inlet" in enabled["enabled"], enabled

    all_cam = _decode_tool_result(await set_camera.handler({"preset": "+z"}))
    inlet_cam = _decode_tool_result(
        await set_camera.handler({"preset": "+z", "patch": "patch/inlet"})
    )

    assert inlet_cam["focal"] != all_cam["focal"], (
        "framing the inlet patch left the focal point on the whole-domain "
        "centre — the patch bounds were not used"
    )
    assert _cam_distance(inlet_cam) < _cam_distance(all_cam), (
        "framing the inlet patch did not zoom closer than framing the case"
    )


@pytest.mark.asyncio
async def test_set_camera_multiple_patches_frame_union(live_bridge):
    """A list of patches frames their combined bounds.

    `inlet` and `outlet` sit at opposite ends of the domain, so framing both
    must zoom out wider than framing `inlet` alone — the union spans more.
    """
    enabled = _decode_tool_result(
        await set_openfoam_patches.handler(
            {"enable": ["patch/inlet", "patch/outlet"]}
        )
    )
    assert {"patch/inlet", "patch/outlet"} <= set(enabled["enabled"]), enabled

    inlet_cam = _decode_tool_result(
        await set_camera.handler({"preset": "+z", "patch": "patch/inlet"})
    )
    both_cam = _decode_tool_result(
        await set_camera.handler(
            {"preset": "+z", "patch": ["patch/inlet", "patch/outlet"]}
        )
    )

    assert _cam_distance(both_cam) > _cam_distance(inlet_cam), (
        "framing inlet+outlet did not zoom wider than inlet alone — the "
        "patch bounds were not unioned"
    )


@pytest.mark.asyncio
async def test_extract_block_accepts_slashed_patch_name(live_bridge):
    """`extract_block` works with the name form `get_openfoam_patches` reports.

    Regression for the selector bug: `'patch/inlet'` (slashed) used to resolve
    to an empty source while only the bare leaf `'inlet'` worked. Both forms
    must now pull the loaded patch's real geometry.
    """
    reader_id = _decode_tool_result(await get_pipeline.handler({}))[0]["id"]
    _decode_tool_result(
        await set_openfoam_patches.handler(
            {"enable": ["patch/inlet"], "input_id": reader_id}
        )
    )

    for name in ("patch/inlet", "inlet"):
        eb = _decode_tool_result(
            await extract_block.handler({"name": name, "input_id": reader_id})
        )
        info = _decode_tool_result(
            await get_source_info.handler({"input_id": eb["id"]})
        )
        assert info["num_cells"] > 0, (
            f"extract_block({name!r}) produced an empty source "
            f"({info['num_cells']} cells) — selector did not resolve the patch"
        )


@pytest.mark.asyncio
async def test_extract_block_empty_reports_count_and_hint(live_bridge):
    """An empty extraction is visible, not silent.

    Extracting a patch that is never loaded must come back with zero counts and
    an actionable `hint` pointing at set_openfoam_patches — so the agent knows
    why a later screenshot would be blank instead of giving up. `flange_patch3`
    is enabled by no other test in this module.
    """
    reader_id = _decode_tool_result(await get_pipeline.handler({}))[0]["id"]
    eb = _decode_tool_result(
        await extract_block.handler(
            {"name": "patch/flange_patch3", "input_id": reader_id}
        )
    )
    assert eb["num_cells"] == 0 and eb["num_points"] == 0, eb
    assert "set_openfoam_patches" in eb.get("hint", ""), eb


@pytest.mark.asyncio
async def test_set_read_zero_time_surfaces_zero_dir_fields(live_bridge):
    """The reader hides 0/ fields by default; set_read_zero_time reveals them.

    The sample case's only time dir is `0/` and it holds checkMesh quality
    fields (skewness, …). With Skip-Zero-Time on (the default), get_source_info
    reports no arrays plus a hint; enabling zero time surfaces them. Disables
    first so the test is independent of any earlier toggle in the module.
    """
    pipeline = _decode_tool_result(await get_pipeline.handler({}))
    reader_id = next(e["id"] for e in pipeline if "FOAM" in e["type"].upper())

    _decode_tool_result(
        await set_read_zero_time.handler({"enable": False, "input_id": reader_id})
    )
    before = _decode_tool_result(await get_source_info.handler({"input_id": reader_id}))
    assert before["cell_arrays"] == [] and before["point_arrays"] == [], before
    assert "set_read_zero_time" in before.get("hint", ""), before

    res = _decode_tool_result(
        await set_read_zero_time.handler({"enable": True, "input_id": reader_id})
    )
    assert res["read_zero_time"] is True, res
    assert "skewness" in res["cell_arrays"], res

    after = _decode_tool_result(await get_source_info.handler({"input_id": reader_id}))
    assert "skewness" in [a["name"] for a in after["cell_arrays"]], after
    assert "hint" not in after, after


@pytest.mark.asyncio
async def test_highlight_problem_cells_cellset_extracts_exact_count(live_bridge):
    """A cellSet maps 1:1 to internalMesh cells and extracts as a new source.

    `underdeterminedCells` lists 21 cells in OpenFOAM internal numbering; the
    reader preserves that numbering, so the overlay must contain exactly 21
    cells and be a fresh source (not a mutation of the reader).
    """
    _decode_tool_result(
        await set_openfoam_patches.handler({"enable": ["internalMesh"]})
    )
    out = _decode_tool_result(
        await highlight_problem_cells.handler({"set_name": "underdeterminedCells"})
    )
    assert out["kind"] == "cellSet", out
    assert out["num_in_set"] == 21, out
    assert out["num_cells_extracted"] == 21, out
    assert out["id"], out  # a real, frameable source
    assert "hint" not in out, out  # counts matched → no mismatch warning


@pytest.mark.asyncio
async def test_highlight_problem_cells_faceset_maps_to_owner_cells(live_bridge):
    """A faceSet is rendered via its faces' owner cells, as points by default.

    `warpedFaces` lists 9 faces; each maps to its owner cell (9 distinct here),
    so the overlay carries 9 cell-center points and the result spells out the
    owner-cell substitution so the agent is not surprised.
    """
    _decode_tool_result(
        await set_openfoam_patches.handler({"enable": ["internalMesh"]})
    )
    out = _decode_tool_result(
        await highlight_problem_cells.handler({"set_name": "warpedFaces"})
    )
    assert out["kind"] == "faceSet", out
    assert out["num_in_set"] == 9, out
    assert out["num_cells_extracted"] == 9, out
    assert "owner cell" in out.get("note", ""), out


@pytest.mark.asyncio
async def test_highlight_problem_cells_reads_gzipped_set(live_bridge):
    """A set that exists only as `<name>.gz` is found and parsed transparently.

    checkMesh sometimes writes compressed sets; the resolver tries the plain
    name then `.gz`, and the parser decompresses. Write a gzipped copy of a
    known cellSet under a fresh name so only the `.gz` form exists.
    """
    import gzip

    project_dir = live_bridge
    sets_dir = project_dir / "Case" / "constant" / "polyMesh" / "sets"
    src = (sets_dir / "underdeterminedCells").read_bytes()
    (sets_dir / "gzOnlyCells.gz").write_bytes(gzip.compress(src))

    _decode_tool_result(
        await set_openfoam_patches.handler({"enable": ["internalMesh"]})
    )
    out = _decode_tool_result(
        await highlight_problem_cells.handler({"set_name": "gzOnlyCells"})
    )
    assert out["kind"] == "cellSet", out
    assert out["num_cells_extracted"] == 21, out


@pytest.mark.asyncio
async def test_highlight_problem_cells_reads_binary_set(live_bridge):
    """A binary-format set is parsed via its FoamFile header, not ASCII split.

    Meshes written with `writeFormat binary` store sets (and `owner`) as packed
    bytes. The parser must read the header to learn format=binary + the label
    width/endianness from `arch`, then unpack exactly `count` labels by length
    (never scanning for ')'). Guards the binary path the faceSet owner-mapping
    also depends on — same parser. IDs 0..11 are valid internal cells.
    """
    import struct

    project_dir = live_bridge
    sets_dir = project_dir / "Case" / "constant" / "polyMesh" / "sets"
    ids = list(range(12))
    header = (
        "FoamFile\n{\n"
        "    version 2.0;\n"
        "    format binary;\n"
        "    class cellSet;\n"
        '    arch "LSB;label=32;scalar=64";\n'
        "    object binaryCells;\n"
        "}\n"
    ).encode("ascii")
    payload = (
        f"{len(ids)}\n(".encode("ascii")
        + struct.pack(f"<{len(ids)}i", *ids)
        + b")\n"
    )
    (sets_dir / "binaryCells").write_bytes(header + payload)

    _decode_tool_result(
        await set_openfoam_patches.handler({"enable": ["internalMesh"]})
    )
    out = _decode_tool_result(
        await highlight_problem_cells.handler({"set_name": "binaryCells"})
    )
    assert out["kind"] == "cellSet", out
    assert out["num_cells_extracted"] == len(ids), out


@pytest.mark.asyncio
async def test_highlight_problem_cells_ascii_data_under_binary_header(live_bridge):
    """A set whose header says `format binary` but whose data is ASCII parses.

    OpenFOAM's topoSet/checkMesh stamp `format binary` into a set's FoamFile
    header (inheriting the case's writeFormat) while writing the label list as
    plain ASCII. Trusting the header would frombuffer the ASCII text as int32 →
    garbage IDs → 0 cells extracted. The parser must sniff the data instead.
    Regression for a real snappyHexMesh case that extracted 0 of 24576 cells.
    """
    project_dir = live_bridge
    sets_dir = project_dir / "Case" / "constant" / "polyMesh" / "sets"
    ids = list(range(15))
    content = (
        "FoamFile\n{\n"
        "    version 2.0;\n"
        "    format binary;\n"  # header lies — data below is ASCII
        "    class cellSet;\n"
        '    arch "LSB;label=32;scalar=64";\n'
        "    object liarCells;\n"
        "}\n"
        f"{len(ids)}\n(\n" + "\n".join(str(i) for i in ids) + "\n)\n"
    )
    (sets_dir / "liarCells").write_text(content)

    _decode_tool_result(
        await set_openfoam_patches.handler({"enable": ["internalMesh"]})
    )
    out = _decode_tool_result(
        await highlight_problem_cells.handler({"set_name": "liarCells"})
    )
    assert out["kind"] == "cellSet", out
    assert out["num_in_set"] == len(ids), out
    assert out["num_cells_extracted"] == len(ids), out  # was 0 before the sniff fix


@pytest.mark.asyncio
async def test_highlight_problem_cells_missing_set_errors(live_bridge):
    """An unknown set name fails loudly and points at checkMesh/topoSet."""
    result = await highlight_problem_cells.handler({"set_name": "no_such_set"})
    assert result.get("is_error"), "expected an error for a missing set"
    msg = result["content"][0]["text"]
    assert "no_such_set" in msg and "checkMesh" in msg, msg


@pytest.mark.asyncio
async def test_highlight_problem_cells_solid_over_field_coloring(live_bridge):
    """The overlay stays solid-coloured even when the reader carries fields.

    With cell arrays present, ParaView auto-colours a fresh extraction by a
    field — which would hide the red highlight behind a colourmap. The tool
    must disable scalar colouring so the solid colour wins. Regression for the
    `ColorBy(rep, None)` fix; only reproducible once arrays are loaded, so this
    enables the case's zero-time quality fields first.
    """
    pipeline = _decode_tool_result(await get_pipeline.handler({}))
    reader_id = next(e["id"] for e in pipeline if "FOAM" in e["type"].upper())
    _decode_tool_result(
        await set_read_zero_time.handler({"enable": True, "input_id": reader_id})
    )
    _decode_tool_result(
        await set_openfoam_patches.handler(
            {"enable": ["internalMesh"], "input_id": reader_id}
        )
    )
    out = _decode_tool_result(
        await highlight_problem_cells.handler({"set_name": "underdeterminedCells"})
    )
    # Read the overlay's colour-array binding from its display. paraview_exec
    # returns repr(result), so compute the verdict inside the script: 'cleared'
    # when no array drives the colour, else the offending array name.
    probe = _decode_tool_result(
        await paraview_exec.handler(
            {
                "code": (
                    "from paraview.simple import "
                    "GetActiveView, GetDisplayProperties, GetSources\n"
                    f"src = [p for (n, g), p in GetSources().items() "
                    f"if g == '{out['id']}'][0]\n"
                    "rep = GetDisplayProperties(src, view=GetActiveView())\n"
                    "arr = list(rep.ColorArrayName)[1]\n"
                    "result = 'cleared' if arr in ('', None) else arr"
                )
            }
        )
    )
    # repr('cleared') == "'cleared'"
    assert probe["result"] == "'cleared'", (
        f"overlay is colour-by-array ({probe['result']}) — the solid red "
        f"highlight would be hidden; ColorBy(None) failed to clear it"
    )


@pytest.mark.asyncio
async def test_probe_point_returns_field_values_without_crashing(live_bridge):
    """probe_point samples fields at a point and survives on OpenFOAM data.

    Regression for the segfault behind the flange-internal-flow-2 crash: the
    old implementation did servermanager.Fetch(probe) + GetTuple(). On this
    multiblock OpenFOAM case the fetched arrays come back with corrupted names
    ("float") and dead data pointers, so GetTuple() SIGSEGVs and kills the
    whole bridge (an uncatchable crash, surfaced to the agent as an opaque
    RemoteDisconnected). The fix reads values from the proxy DataInformation
    instead, which is computed ParaView-side and never touches that memory.

    Loads the case's 0/ fields first so there are real arrays (U, p, k, ...)
    to exercise the value-reading path, then probes the domain centre.
    """
    pipeline = _decode_tool_result(await get_pipeline.handler({}))
    reader_id = next(e["id"] for e in pipeline if "FOAM" in e["type"].upper())
    _decode_tool_result(
        await set_read_zero_time.handler({"enable": True, "input_id": reader_id})
    )
    info = _decode_tool_result(await get_source_info.handler({"input_id": reader_id}))

    out = _decode_tool_result(
        await probe_point.handler({"point": info["center"], "input_id": reader_id})
    )
    assert "arrays" in out and "valid" in out, out
    # The point is the bounding-box centre of a real OpenFOAM mesh, so the
    # sampled fields must include the velocity and pressure that get_source_info
    # reported on the reader — proof the value-read path actually ran.
    assert "U" in out["arrays"] and "p" in out["arrays"], out
    assert isinstance(out["arrays"]["U"], list) and len(out["arrays"]["U"]) == 3, out

    # The real proof it survived: the bridge still answers.
    ping_out = _decode_tool_result(await ping.handler({}))
    assert ping_out.get("ok") is True, "bridge died after a single probe"


@pytest.mark.asyncio
async def test_integrate_variables_returns_named_integrals_without_crashing(live_bridge):
    """integrate_variables returns correctly-named integrals and survives.

    Same root cause as probe_point: the old implementation did
    servermanager.Fetch(iv) + GetTuple(), which segfaults on corrupt OpenFOAM
    multiblock arrays. The fix reads the single-element IntegrateVariables
    output from DataInformation (computed ParaView-side), which both avoids the
    crash and keeps real field names (the fetched arrays collapse to "float").
    """
    pipeline = _decode_tool_result(await get_pipeline.handler({}))
    reader_id = next(e["id"] for e in pipeline if "FOAM" in e["type"].upper())
    _decode_tool_result(
        await set_read_zero_time.handler({"enable": True, "input_id": reader_id})
    )

    out = _decode_tool_result(
        await integrate_variables.handler({"input_id": reader_id})
    )
    integrals = out["integrals"]
    # Real field names, not the corrupted VTK type name "float".
    assert "U" in integrals and "p" in integrals, integrals
    assert "float" not in integrals, integrals
    # A 3D OpenFOAM internalMesh integrates to a positive volume.
    assert isinstance(out["volume_or_area"], (int, float)), out
    assert out["volume_or_area"] > 0, out

    ping_out = _decode_tool_result(await ping.handler({}))
    assert ping_out.get("ok") is True, "bridge died during integrate_variables"


@pytest.mark.asyncio
async def test_concurrent_probe_points_do_not_crash_paraview(live_bridge):
    """A batch of concurrent probe_point calls must not kill ParaView.

    The flange-internal-flow-2 crash happened on a turn that fired five
    probe_point calls at once. Each handler awaits bridge_call ->
    asyncio.to_thread, so a batch hits the bridge as simultaneous POSTs;
    asyncio.gather here reproduces that. (The crash was actually the
    Fetch/GetTuple segfault in each probe, not the concurrency itself — but
    a batch is exactly how the agent triggers it, so it is the regression
    case worth guarding.)

    Assertion is liveness: every probe returns without a transport error and
    the bridge still answers /ping. A crash returns RemoteDisconnected /
    Connection refused.
    """
    pipeline = _decode_tool_result(await get_pipeline.handler({}))
    reader_id = next(e["id"] for e in pipeline if "FOAM" in e["type"].upper())
    _decode_tool_result(
        await set_read_zero_time.handler({"enable": True, "input_id": reader_id})
    )
    info = _decode_tool_result(await get_source_info.handler({"input_id": reader_id}))
    cx, cy, cz = info["center"]
    b = info["bounds"]
    # Eight points strung along the x-extent through the domain centre.
    xs = [b[0] + (b[1] - b[0]) * (k + 1) / 9 for k in range(8)]
    points = [[x, cy, cz] for x in xs]

    results = await asyncio.gather(
        *(
            probe_point.handler({"point": p, "input_id": reader_id})
            for p in points
        ),
        return_exceptions=True,
    )

    for p, res in zip(points, results):
        assert not isinstance(res, Exception), f"probe_point({p}) raised {res!r}"
        assert not res.get("is_error"), (
            f"probe_point({p}) failed — ParaView likely crashed under the "
            f"concurrent batch: {res['content'][0]['text']}"
        )

    # The real proof it survived: the bridge still answers.
    out = _decode_tool_result(await ping.handler({}))
    assert out.get("ok") is True, "bridge unreachable after concurrent probes"


@pytest.mark.asyncio
async def test_set_camera_unknown_patch_errors(live_bridge):
    """A genuinely unknown patch name fails loudly and lists valid names.

    (Known-but-unloaded patches now auto-load instead of erroring — see
    test_set_camera_autoloads_unloaded_patch.) For a name that matches no
    region the error must list the available patches inline and point at
    get_openfoam_patches, so the agent can self-correct without a lookup.
    """
    result = await set_camera.handler({"patch": "no_such_patch"})
    assert result.get("is_error"), "expected an error for an unknown patch"
    msg = result["content"][0]["text"]
    assert "no_such_patch" in msg and "get_openfoam_patches" in msg, msg
    assert "available:" in msg and "patch/inlet" in msg, msg


@pytest.mark.asyncio
async def test_set_camera_unloaded_patch_errors_with_enable_hint(live_bridge):
    """A known-but-unloaded patch errors with the exact enable call, no mutation.

    set_camera is a view operation and must not silently load data. Naming a
    patch that exists but isn't loaded fails with a precise one-step fix — the
    set_openfoam_patches(enable=[...]) call needed — and crucially leaves the
    reader's loaded regions unchanged. (A genuinely unknown name gets the
    different 'no patch named' error; see test_set_camera_unknown_patch_errors.)
    """
    pipeline = _decode_tool_result(await get_pipeline.handler({}))
    reader_id = next(e["id"] for e in pipeline if "FOAM" in e["type"].upper())
    # Force the patch unloaded first, independent of earlier tests.
    enabled_before = _decode_tool_result(
        await set_openfoam_patches.handler(
            {"disable": ["patch/outlet"], "input_id": reader_id}
        )
    )["enabled"]
    assert "patch/outlet" not in enabled_before, enabled_before

    result = await set_camera.handler(
        {"preset": "+z", "patch": "outlet", "id": reader_id}
    )
    assert result.get("is_error"), "expected an error for an unloaded patch"
    msg = result["content"][0]["text"]
    assert "not loaded" in msg and "set_openfoam_patches" in msg, msg
    assert "patch/outlet" in msg, msg  # the exact selector to enable

    # It must NOT have silently loaded the patch.
    enabled_after = _decode_tool_result(
        await set_openfoam_patches.handler({"input_id": reader_id})
    )["enabled"]
    assert "patch/outlet" not in enabled_after, enabled_after
