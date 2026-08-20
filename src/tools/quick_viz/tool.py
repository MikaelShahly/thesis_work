"""quick_viz — one-shot headless ParaView render tool.

Wraps the renderer in ``quick_vizualization/viz/render.py``: the agent
passes an inline YAML config, the tool writes it to a temp file, runs
``pvbatch`` fully offscreen with the project directory as cwd (so the
config's relative paths resolve against the project root), and returns
the renderer's JSON result.

Two build-specific facts drive the implementation:

- ``pvbatch`` on this ParaView build exits NONZERO from a benign
  interpreter-teardown crash that fires AFTER the PNG/.pvsm are written
  and the result line is printed. So success is decided by the presence
  of the JSON result on stdout — never by the exit code.
- An in-process MCP tool can't discover which project it's running in
  (the backend never chdirs to the project). So, like ``web_fetch``,
  the tool object is built per turn bound to the project dir via
  ``make_quick_viz`` rather than being a static singleton.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool


# render.py + its sibling modules (camera/colors/miniyaml) live in the
# repo's quick_vizualization/ bundle and are run by pvbatch's OWN Python,
# not the backend interpreter. parents: [0]=quick_viz [1]=tools [2]=src
# [3]=repo root.
_RENDER_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "quick_vizualization" / "viz" / "render.py"
)

# Generous ceiling: a heavy slice + percentile fetch on a large mesh can
# take a couple of minutes. Well under any phase-level limit.
_TIMEOUT_S = 300.0

QUICK_VIZ_TOOL = "quick_viz"


def _pvbatch() -> str:
    """The pvbatch executable. Override with ``QUICKVIZ_PVBATCH`` for
    unusual installs; defaults to ``pvbatch`` on PATH (mirrors the
    ``PARAVIEW_EXECUTABLE`` convention in src/paraview/lifecycle.py)."""
    return os.environ.get("QUICKVIZ_PVBATCH", "pvbatch")


def _run_render(config_text: str, project_dir: Path) -> dict[str, Any]:
    """Run pvbatch on the inline config. Returns the renderer's result
    dict on success, or ``{"error": <msg>}`` on failure. Synchronous —
    call via ``asyncio.to_thread``."""
    with tempfile.NamedTemporaryFile(
        "w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        f.write(config_text)
        cfg_path = f.name
    try:
        proc = subprocess.run(
            [
                _pvbatch(), "--force-offscreen-rendering",
                str(_RENDER_SCRIPT), cfg_path,
            ],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
        )
    except FileNotFoundError:
        return {"error": (
            f"pvbatch not found (looked for {_pvbatch()!r}). Set the "
            "QUICKVIZ_PVBATCH environment variable to the pvbatch path."
        )}
    except subprocess.TimeoutExpired:
        return {"error": f"render timed out after {_TIMEOUT_S:.0f}s"}
    finally:
        try:
            os.unlink(cfg_path)
        except OSError:
            pass

    # Success == the JSON result line on stdout. The exit code is
    # unreliable (benign teardown crash after the result is printed), so
    # scan stdout for the renderer's `{... "output" ...}` line instead.
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and '"output"' in line:
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                break
    return {"error": (
        proc.stderr.strip() or proc.stdout.strip()
        or "render produced no output"
    )}


_DESCRIPTION = (
    "Headless ParaView render of an OpenFOAM case/mesh or raw geometry -> "
    "a PNG + a reopenable .pvsm, for mesh-quality and field inspection. "
    "Pass an inline YAML `config` (full schema below); returns "
    "`{output, state, coloring}` -- Read the output PNG to view it. "
    "`coloring` reports per field-colored element {field, mode, "
    "colored_range, data_range, note?}; `note` warns when the range "
    "clamps a peak (re-run with range: auto). Config paths are relative "
    "to the project dir.\n\n"
    "CONFIG -- `output:` required, plus `case:` and/or `geometry:`; "
    "everything else optional, defaults shown:\n\n"
    "output: <png path>     # REQUIRED; the .pvsm is written alongside it\n"
    "case: <case dir>\n"
    "geometry: [{file: <path>, opacity: 1.0, representation: <override>, split_regions: true}]"
    "  # STL/OBJ/PLY/VTK/VTP/VTU; split_regions (ASCII multi-solid STL only) -> one colored+legended region per solid\n"
    "time: latest           # latest|first|<value> (nearest). 0/ is read only when resolved time==0 -> quality fields in 0/ need time:0; solver fields use latest\n"
    "size: [1920, 1080]\n"
    "representation: surface_with_edges"
    "  # surface|surface_with_edges|wireframe|feature_edges|points; per-entity override allowed. wireframe/feature_edges = grey context cage (no legend row); points -> set point_size\n"
    "legend: false          # true|false -> categorical key (swatch + entity name per row) for SOLID-colored entities; field coloring gets a scalar bar instead\n"
    "focus: [<name>...]     # color only these, mute the rest grey. name = patch | \"file.stl:region\" | set | \"internal:<type>\"\n"
    "view:\n"
    "  preset: iso          # xy|xz|yz|+x|-x|+y|-y|+z|-z|[x,y,z]  (vector = direction the camera looks FROM)\n"
    "  frame: all           # [<name>...] -> fit those (patch|set|filename|\"internal:slice|clip|threshold\")\n"
    "boundaries:            # needs case. flat [{patch: w}] OR {color_by:{...}, patches:[...]}\n"
    "  color_by: {field: <f>, cmap: \"Viridis (matplotlib)\", range: p2_p98, scalar_bar: true}"
    "  # shared by listed patches. range: p2_p98 (spreads bulk, clamps tail) | auto (true min/max) | [min,max] | pLO_pHI. cmap = any ParaView preset name\n"
    "  patches: [{patch: <name>, opacity: 1.0, representation: <ovr>, mute: false, point_size: <n>, color_by: false}]"
    "  # mute -> opacity<=0.18; color_by:false opts that patch out of block coloring\n"
    "internal:              # needs case. VTK pipeline from internalMesh\n"
    "  show: false          # true with no filters = full opaque volume\n"
    "  filters:             # applied in order; each feeds the next\n"
    "    - {type: slice,         normal: z|x|y|[nx,ny,nz], origin: <bbox center>}\n"
    "    - {type: clip,          normal: , origin: , invert: <auto: keep half away from camera>}\n"
    "    - {type: threshold,     field: , range: [lo, hi], invert: false}   # null on a side = unbounded\n"
    "    - {type: crinkle_slice, normal: , origin: }                        # whole intersected cells\n"
    "  color_by: {field: , cmap: , range: , scalar_bar: }   # omit -> solid color + edges\n"
    "  opacity: 1.0\n"
    "  representation: <ovr>\n"
    "  point_size: <n>\n"
    "overlays:              # needs case\n"
    "  problem_cells: [{set: <cellSet in constant/polyMesh/sets>, opacity: 1.0, representation: <ovr>, point_size: <n>}]   # cellSet only\n\n"
    "color_by.field = any cell/point field present at that time (vector -> magnitude); "
    "on a miss the tool returns the available fields. "
    "Quality fields (skewness, nonOrthoAngle, cellAspectRatio, cellVolume) need "
    "`checkMesh -writeFields '(...)'` first; yPlus/wallShearStress need a solver run. "
    "Solid colors are auto-assigned (deterministic) -- you don't set them."
)

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "config": {
            "type": "string",
            "description": "The render config as a YAML string (schema in this tool's description).",
        },
    },
    "required": ["config"],
}


def make_quick_viz(project_dir: Path):
    """Build a ``quick_viz`` tool object bound to ``project_dir``.

    pvbatch runs with ``project_dir`` as cwd, so the config's relative
    paths (``case: Case/``, ``geometry: [{file: ...}]``) resolve against
    the project root — the same root the agent sees. Built per turn
    because an in-process tool can't discover the project itself."""

    @tool(QUICK_VIZ_TOOL, _DESCRIPTION, _INPUT_SCHEMA)
    async def quick_viz(args: dict[str, Any]) -> dict[str, Any]:
        config_text = args.get("config")
        if not config_text or not str(config_text).strip():
            return {
                "content": [{
                    "type": "text",
                    "text": "quick_viz requires a non-empty `config` YAML string.",
                }],
                "is_error": True,
            }
        result = await asyncio.to_thread(
            _run_render, str(config_text), project_dir
        )
        if "error" in result:
            return {
                "content": [{
                    "type": "text",
                    "text": f"quick_viz render failed: {result['error']}",
                }],
                "is_error": True,
            }
        return {
            "content": [{
                "type": "text",
                "text": json.dumps(result, default=str),
            }],
        }

    return quick_viz
