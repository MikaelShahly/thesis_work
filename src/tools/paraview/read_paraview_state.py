"""Read-only ParaView bridge tools.

Every verb here observes ParaView state without mutating it. Each tool
body is a one-liner over `bridge_call("/<verb>", {...})`; the file
classification (this module vs. `change_paraview_state.py`) drives the
`PARAVIEW_READ_TOOLS` constant in `__init__.py`.
"""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import tool

from src.tools.paraview._client import bridge_call


# ── ping ───────────────────────────────────────────────────────────────
@tool(
    "ping",
    (
        "Confirm the ParaView bridge is reachable and learn the active "
        "project root. Returns `{ok: true, project_root: <abs path>}` "
        "on success.\n\n"
        "**Always call this first** when you have not yet used a "
        "ParaView verb in the current turn. Two reasons:\n"
        "1. Distinguishes 'ParaView is not open' from 'a specific verb "
        "failed' — if this errors with 'bridge unreachable', ask the "
        "user to open ParaView via the toolbar button.\n"
        "2. The returned `project_root` is the directory that "
        "**relative paths in `save_screenshot` and `load_dataset` "
        "anchor on**. Remember it for the rest of the turn so you "
        "know where files will land."
    ),
    {"type": "object", "properties": {}},
)
async def ping(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/ping", {})


# ── get_pipeline ───────────────────────────────────────────────────────
@tool(
    "get_pipeline",
    (
        "Return the current ParaView pipeline as a list of "
        "`{id, name, type, input_ids, visible, active}` entries. The "
        "`id` is the global proxy id used by every other verb that "
        "targets a specific source (`set_active_source`, "
        "`delete_source`, `*_filter --input-id`). `input_ids` lets you "
        "reconstruct the DAG. `active` marks the one source that verbs "
        "default to when you omit `input_id` — note that "
        "`paraview_exec` and creating a filter can silently move it, so "
        "check `active` before relying on a default-targeted verb. "
        "Lightweight — call it freely to orient yourself."
    ),
    {"type": "object", "properties": {}},
)
async def get_pipeline(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/get_pipeline", {})


# ── get_source_info ────────────────────────────────────────────────────
@tool(
    "get_source_info",
    (
        "Discovery tool for a single source. Returns bounds, center, "
        "point/cell counts, memory, the per-source `point_arrays` and "
        "`cell_arrays` (each with name, components, range), the "
        "settable `properties` block (mirrors ParaView's GUI Properties "
        "panel), and the current `display` state. If both array lists "
        "are empty the case has no solver fields loaded — only the "
        "mesh; any `--array X` filter will then fail. OpenFOAM solver "
        "fields (U, p, T, k, omega, nut) live on CELLS.\n\n"
        "Targets the active source unless `input_id` is supplied."
    ),
    {
        "type": "object",
        "properties": {
            "input_id": {
                "type": "string",
                "description": (
                    "Optional source id from `get_pipeline`. Omit to "
                    "target the active source."
                ),
            },
        },
    },
)
async def get_source_info(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/get_source_info", args)


# ── get_workspace ──────────────────────────────────────────────────────
@tool(
    "get_workspace",
    (
        "Return the view/layout layer: list of views (with id, type, "
        "view_size), list of layouts, the active view/source/layout "
        "ids, and the current selection summary. Use this to find a "
        "view id for `set_active_view` and to get a broad orientation."
    ),
    {"type": "object", "properties": {}},
)
async def get_workspace(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/get_workspace", {})


# ── get_time ───────────────────────────────────────────────────────────
@tool(
    "get_time",
    (
        "Return `{current, available, step_count}` for the active view. "
        "`available` is the list of timestep values; `current` is the "
        "active view's `ViewTime`. Empty `available` means the dataset "
        "is steady-state."
    ),
    {"type": "object", "properties": {}},
)
async def get_time(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/get_time", {})


# ── get_camera ─────────────────────────────────────────────────────────
@tool(
    "get_camera",
    (
        "Return the active view's camera: `position`, `focal`, `up`, "
        "`view_angle`, parallel-projection flag and scale, "
        "`clipping_range`, `view_size`. Useful for capturing the "
        "current camera before a destructive `set_camera` so it can be "
        "restored."
    ),
    {"type": "object", "properties": {}},
)
async def get_camera(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/get_camera", {})


# ── get_selection_info ─────────────────────────────────────────────────
@tool(
    "get_selection_info",
    (
        "Return information about the user's interactive selection in "
        "ParaView (drag-select, click-pick, Find Data). Returns "
        "`{active: false}` if nothing is selected. When active, "
        "returns `{field, method, count, color_rgb, bbox, "
        "blocks_touched, array_ranges}`.\n\n"
        "Set `stats: true` to additionally compute min/max and a "
        "volume/area-weighted mean over each array on the selection (or "
        "just `array` if supplied) — slower; off by default."
    ),
    {
        "type": "object",
        "properties": {
            "stats": {
                "type": "boolean",
                "description": "If true, include per-array statistics.",
            },
            "array": {
                "type": "string",
                "description": (
                    "Restrict statistics to this array name only "
                    "(only meaningful when `stats` is true)."
                ),
            },
        },
    },
)
async def get_selection_info(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/get_selection_info", args)


# ── probe_point ────────────────────────────────────────────────────────
@tool(
    "probe_point",
    (
        "Sample the source's fields at a single 3D point. Returns "
        "`{point, valid, arrays}` where `arrays` maps each field name "
        "(U, p, k, ...) to its sampled value at that location. `valid` "
        "is false when the point falls outside the dataset (the values "
        "are then unset).\n\n"
        "Targets the active source unless `input_id` is supplied."
    ),
    {
        "type": "object",
        "properties": {
            "point": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "World-space coordinate [x, y, z].",
            },
            "input_id": {
                "type": "string",
                "description": (
                    "Optional source id; defaults to the active source."
                ),
            },
        },
        "required": ["point"],
    },
)
async def probe_point(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/probe_point", args)


# ── integrate_variables ────────────────────────────────────────────────
@tool(
    "integrate_variables",
    (
        "Run ParaView's IntegrateVariables filter and return the "
        "spatial integral of every array on the source plus the total "
        "volume or area. Useful for force/flux summaries on extracted "
        "patches.\n\n"
        "Targets the active source unless `input_id` is supplied."
    ),
    {
        "type": "object",
        "properties": {
            "input_id": {
                "type": "string",
                "description": (
                    "Optional source id; defaults to the active source."
                ),
            },
        },
    },
)
async def integrate_variables(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/integrate_variables", args)


# ── save_screenshot ────────────────────────────────────────────────────
@tool(
    "save_screenshot",
    (
        "Render the active view and save it as a PNG. Aspect ratio "
        "matches the live view; long edge is 1600 px. Returns "
        "`{path, resolution}` — `path` is the resolved absolute "
        "destination, so you can confirm where it landed.\n\n"
        "By default the active source's interactive widget (the "
        "draggable plane / box / line handles attached to filters "
        "like Clip, Slice, Glyph) is hidden during capture and "
        "restored after — pass `hide_widgets: false` to keep it "
        "visible in the screenshot.\n\n"
        "**Path semantics.** A relative `out_path` is resolved against "
        "the **active project's root directory** (the value of "
        "`project_root` returned by `ping`). You choose where the render "
        "lands — pick a location that fits the project layout and the "
        "work at hand (e.g. alongside the case it illustrates). So with a "
        "project at `/path/to/projects/cylinder/`, "
        "`out_path='Cases/baseline/u_mag.png'` writes to "
        "`/path/to/projects/cylinder/Cases/baseline/u_mag.png`. Missing "
        "intermediate directories are created. Absolute paths are "
        "honoured as-is."
    ),
    {
        "type": "object",
        "properties": {
            "out_path": {
                "type": "string",
                "description": (
                    "Destination PNG path. Project-relative is the "
                    "norm, e.g. 'Cases/baseline/initial_mesh.png'."
                ),
            },
            "hide_widgets": {
                "type": "boolean",
                "description": (
                    "Hide the active source's interactive widget "
                    "(filter manipulator handles) during capture. "
                    "Default true."
                ),
            },
        },
        "required": ["out_path"],
    },
)
async def save_screenshot(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/save_screenshot", args)


# ── get_openfoam_patches ───────────────────────────────────────────────
@tool(
    "get_openfoam_patches",
    (
        "Return `{enabled, available}` for the OpenFOAM reader's "
        "`MeshRegions` property — which patches/regions are currently "
        "loaded vs. all patches the case exposes. Use before "
        "`set_openfoam_patches` to know what the user has on now and "
        "what names are valid.\n\n"
        "Errors if no OpenFOAMReader is in the pipeline. Pass "
        "`input_id` if there are multiple readers."
    ),
    {
        "type": "object",
        "properties": {
            "input_id": {
                "type": "string",
                "description": (
                    "Optional source id of the target OpenFOAM reader; "
                    "defaults to the first one in the pipeline."
                ),
            },
        },
    },
)
async def get_openfoam_patches(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/get_openfoam_patches", args)


# Module-level list of (tool_id, tool_callable) pairs the package
# `__init__.py` consumes when assembling the registry. Order is the
# order tools appear in the agent's visible list — keep it stable so
# prompt and tests can reference it predictably.
# NOTE: `export_snapshot` (the bridge's full-state JSON-plus-PNG
# bundle) is intentionally NOT exposed here. The plan is to wire it
# from the frontend so the user can hand the LLM a snapshot of the
# current ParaView scene; it is not a tool the agent calls itself.
# The bridge endpoint stays available for that future route.
READ_TOOLS = [
    ("ping", ping),
    ("get_pipeline", get_pipeline),
    ("get_source_info", get_source_info),
    ("get_workspace", get_workspace),
    ("get_time", get_time),
    ("get_camera", get_camera),
    ("get_selection_info", get_selection_info),
    ("probe_point", probe_point),
    ("integrate_variables", integrate_variables),
    ("save_screenshot", save_screenshot),
    ("get_openfoam_patches", get_openfoam_patches),
]
