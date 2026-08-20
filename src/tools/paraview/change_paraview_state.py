"""ParaView bridge tools that mutate scene state.

Pipeline lifecycle (load/create/delete sources, switch active),
filters, display settings, OpenFOAM patch toggles, camera/time, and
selection clearing all live here. The file classification (this
module vs. `read_paraview_state.py`) drives the
`PARAVIEW_WRITE_TOOLS` constant in `__init__.py`.

Each tool body is a one-liner over `bridge_call("/<verb>", {...})`.
Argument key normalisation: callers send `range` and `type`; the
bridge accepts both forms (it rewrites to `range_` / `type_` to dodge
Python keyword clashes), so we send what the model writes.
"""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import tool

from src.tools.paraview._client import bridge_call


# ── Pipeline lifecycle ─────────────────────────────────────────────────
@tool(
    "load_dataset",
    (
        "Open a dataset file in ParaView (`.foam`, `.vtu`, `.vtk`, "
        "`.stl`, `.obj`, `.csv`, …). Adds it to the pipeline, makes "
        "it visible in the active view, resets the camera. Returns "
        "`{id, name, type, path}` for the new source — `path` is the "
        "resolved absolute path, so you can confirm what was loaded.\n\n"
        "**Path semantics.** A relative `path` is resolved against "
        "the **active project's root directory** (the value of "
        "`project_root` returned by `ping`). That root contains the "
        "standard subfolders `Specification/`, `Cases/`, and "
        "`Geometry/`. Typical loads:\n"
        "- `path='Cases/baseline/case.foam'` → an OpenFOAM case the "
        "case-builder wrote (one named subfolder per case under "
        "`Cases/`)\n"
        "- `path='Geometry/cylinder.stl'` → user-uploaded geometry\n\n"
        "Absolute paths are honoured as-is. Use `Bash` (`ls`, `find`) "
        "to discover the available cases under `Cases/` and any other "
        "files — the project root is the bridge's relative-path anchor."
    ),
    {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Path to the dataset file, project-relative or "
                    "absolute."
                ),
            },
            "type": {
                "type": "string",
                "description": (
                    "Optional reader override. Usually omit and let "
                    "ParaView pick by file extension."
                ),
            },
        },
        "required": ["path"],
    },
)
async def load_dataset(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/load_dataset", args)


@tool(
    "create_geometry_source",
    (
        "Create a procedural geometry source: sphere, cone, cylinder, "
        "plane, box, or line. The new source is shown in the active "
        "view. Argument shape varies by `type`:\n"
        "- sphere/cone/cylinder: `center` (vec3), `radius`, `height` "
        "(cone/cylinder only)\n"
        "- plane: `origin`, `point1`, `point2` (each vec3)\n"
        "- line: `point1`, `point2` (each vec3)\n"
        "- box: `bounds` [xmin, xmax, ymin, ymax, zmin, zmax] OR "
        "`center` (vec3)"
    ),
    {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": ["sphere", "cone", "cylinder", "plane", "box", "line"],
            },
            "center": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
            "radius": {"type": "number"},
            "height": {"type": "number"},
            "origin": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
            "point1": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
            "point2": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
            "bounds": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 6,
                "maxItems": 6,
            },
        },
        "required": ["type"],
    },
)
async def create_geometry_source(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/create_geometry_source", args)


@tool(
    "set_active_source",
    (
        "Make the source with the given id the active source. After a "
        "filter creates a new node, that filter becomes active and its "
        "input is hidden — call this to switch focus back to a parent "
        "(e.g. the OpenFOAM reader) before applying another filter to "
        "it."
    ),
    {
        "type": "object",
        "properties": {
            "source_id": {
                "type": "string",
                "description": "Source id from `get_pipeline`.",
            },
        },
        "required": ["source_id"],
    },
)
async def set_active_source(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/set_active_source", args)


@tool(
    "set_active_view",
    (
        "Make the view with the given id the active view. View-scoped "
        "verbs (camera, screenshots, display tweaks) target the active "
        "view; in single-view sessions this is the default RenderView "
        "and you do not need to call this."
    ),
    {
        "type": "object",
        "properties": {
            "view_id": {
                "type": "string",
                "description": "View id from `get_workspace`.",
            },
        },
        "required": ["view_id"],
    },
)
async def set_active_view(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/set_active_view", args)


@tool(
    "delete_source",
    (
        "Remove a source/filter from the pipeline. Returns "
        "`{deleted, re_shown}` — `re_shown` lists ids of input "
        "(parent) sources that were made visible again because they "
        "no longer have any visible downstream consumer. Use to back "
        "out of a failed filter without piling up dead nodes. Any "
        "colour legend orphaned by the deletion is cleared too."
    ),
    {
        "type": "object",
        "properties": {
            "source_id": {
                "type": "string",
                "description": "Source id to delete.",
            },
        },
        "required": ["source_id"],
    },
)
async def delete_source(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/delete_source", args)


# ── Filters ────────────────────────────────────────────────────────────
# Each `apply_*_filter` creates a new pipeline node, makes it active,
# hides its input. Returns `{id, name, type}` for the new node.

@tool(
    "apply_slice_filter",
    (
        "Slice the active source (or `input_id`) with a plane defined "
        "by `normal` and `origin`. If `origin` is omitted the input's "
        "bounding-box centre is used."
    ),
    {
        "type": "object",
        "properties": {
            "normal": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Plane normal (does not need to be unit).",
            },
            "origin": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
            "input_id": {"type": "string"},
        },
        "required": ["normal"],
    },
)
async def apply_slice_filter(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/apply_slice_filter", args)


@tool(
    "apply_clip_filter",
    (
        "Clip the active source with a plane defined by `normal` and "
        "`origin`. If `origin` is omitted the input's bounding-box "
        "centre is used. `invert` flips which side is kept; `crinkle` "
        "keeps whole cells that straddle the plane (good for revealing "
        "internal mesh structure)."
    ),
    {
        "type": "object",
        "properties": {
            "normal": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
            "origin": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
            "invert": {"type": "boolean"},
            "crinkle": {"type": "boolean"},
            "input_id": {"type": "string"},
        },
        "required": ["normal"],
    },
)
async def apply_clip_filter(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/apply_clip_filter", args)


@tool(
    "apply_threshold_filter",
    (
        "Subset cells whose `array` value falls in `[range[0], "
        "range[1]]`. For vector arrays pick a `component` (0/1/2 for "
        "x/y/z, -1 for magnitude). Errors loudly with the available "
        "array names if `array` does not exist on the input."
    ),
    {
        "type": "object",
        "properties": {
            "array": {"type": "string"},
            "range": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
            },
            "component": {"type": "integer"},
            "input_id": {"type": "string"},
        },
        "required": ["array", "range"],
    },
)
async def apply_threshold_filter(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/apply_threshold_filter", args)


@tool(
    "apply_contour_filter",
    (
        "Generate iso-surfaces of `array` at the listed `values`. If "
        "the array lives on cells (the OpenFOAM default) the bridge "
        "auto-inserts a CellDataToPointData node so contouring works."
    ),
    {
        "type": "object",
        "properties": {
            "array": {"type": "string"},
            "values": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 1,
            },
            "input_id": {"type": "string"},
        },
        "required": ["array", "values"],
    },
)
async def apply_contour_filter(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/apply_contour_filter", args)


@tool(
    "apply_glyph_filter",
    (
        "Place glyphs (arrows / spheres / cones / 2d markers / "
        "cylinders) oriented and scaled by `array`. Use `scale` to "
        "rescale globally; cap the count with `max_points`."
    ),
    {
        "type": "object",
        "properties": {
            "array": {"type": "string"},
            "scale": {"type": "number"},
            "type": {
                "type": "string",
                "enum": ["arrow", "sphere", "cone", "2d_glyph", "cylinder"],
            },
            "max_points": {"type": "integer"},
            "input_id": {"type": "string"},
        },
        "required": ["array"],
    },
)
async def apply_glyph_filter(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/apply_glyph_filter", args)


@tool(
    "apply_streamtracer_filter",
    (
        "Trace streamlines through the vector field `array`. Two seed "
        "geometries: `line` (use `p0`/`p1`) or `point_cloud` (use "
        "`center`/`radius`). `direction` controls forward/backward/both."
    ),
    {
        "type": "object",
        "properties": {
            "array": {"type": "string"},
            "seed_type": {
                "type": "string",
                "enum": ["line", "point_cloud", "sphere"],
            },
            "p0": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
            "p1": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
            "center": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
            "radius": {"type": "number"},
            "resolution": {"type": "integer"},
            "max_length": {"type": "number"},
            "direction": {
                "type": "string",
                "enum": ["forward", "backward", "both"],
            },
            "input_id": {"type": "string"},
        },
        "required": ["array", "seed_type"],
    },
)
async def apply_streamtracer_filter(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/apply_streamtracer_filter", args)


@tool(
    "apply_calculator_filter",
    (
        "Compute a derived array via ParaView's Calculator filter. "
        "`result` is the new array name; `expr` is a Calculator "
        "expression (e.g. 'mag(U)' or 'p - 1e5'). `field` selects "
        "point or cell association."
    ),
    {
        "type": "object",
        "properties": {
            "result": {"type": "string"},
            "expr": {"type": "string"},
            "field": {"type": "string", "enum": ["point", "cell"]},
            "input_id": {"type": "string"},
        },
        "required": ["result", "expr"],
    },
)
async def apply_calculator_filter(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/apply_calculator_filter", args)


@tool(
    "compute_gradient_filter",
    (
        "Compute the gradient of `array` (a scalar or vector field). "
        "Adds gradient arrays to the output."
    ),
    {
        "type": "object",
        "properties": {
            "array": {"type": "string"},
            "input_id": {"type": "string"},
        },
        "required": ["array"],
    },
)
async def compute_gradient_filter(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/compute_gradient_filter", args)


@tool(
    "extract_block",
    (
        "Pull a single block out of a multiblock dataset (e.g. one "
        "OpenFOAM patch). `name` is the block/patch name as reported by "
        "`get_openfoam_patches` — either the full path ('patch/walls') "
        "or the bare leaf ('walls'). The patch must be loaded "
        "(`set_openfoam_patches`); extracting an unloaded patch yields "
        "an empty source. Returns `num_cells`/`num_points`, plus a "
        "`hint` when the result is empty.\n\n"
        "Extraction runs on the source you pass as `input_id`. Omit it "
        "and it targets the **active** source — but `paraview_exec` and "
        "filter creation can silently move the active source off the "
        "OpenFOAM reader, so an empty result usually means you extracted "
        "from the wrong source. Pass the OpenFOAMReader's `input_id` "
        "(from `get_pipeline`) to be safe."
    ),
    {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "input_id": {"type": "string"},
        },
        "required": ["name"],
    },
)
async def extract_block(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/extract_block", args)


@tool(
    "extract_surface",
    (
        "Apply the ExtractSurface filter — turn a volume mesh into its "
        "outer surface. Cheap; useful before glyph or contour filters "
        "that only care about the boundary."
    ),
    {
        "type": "object",
        "properties": {
            "input_id": {"type": "string"},
        },
    },
)
async def extract_surface(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/extract_surface", args)


@tool(
    "extract_selection",
    (
        "Materialise the user's interactive selection as a new "
        "pipeline node. Pair with `get_selection_info` to see what "
        "the user has selected before extracting it."
    ),
    {
        "type": "object",
        "properties": {
            "input_id": {"type": "string"},
        },
    },
)
async def extract_selection(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/extract_selection", args)


@tool(
    "highlight_problem_cells",
    (
        "Highlight an OpenFOAM topoSet — typically checkMesh's problem "
        "cells — as a new overlay source so you can see WHERE the bad "
        "cells are. Reads `constant/polyMesh/sets/<set_name>` off disk "
        "(handles `.gz`) and extracts the matching cells of the reader's "
        "`internalMesh` into a fresh, saturated-red source layered on the "
        "scene. **It leaves every existing source untouched** — to make "
        "the overlay pop, dim or hide the base mesh yourself with "
        "`set_opacity`/`set_visibility`, and recolour/restyle the overlay "
        "with `set_solid_color`/`set_representation`. Frame onto it with "
        "`set_camera` (the returned `id` is a normal source).\n\n"
        "- **cellSet** (e.g. `underdeterminedCells`) → those cells.\n"
        "- **faceSet** (e.g. `lowWeightFaces`) → the OWNER CELL of each "
        "face is displayed. A face is the interface between two cells, not "
        "a renderable volume, so this locates each bad face to within one "
        "cell rather than drawing the face itself; the returned `note` "
        "says so.\n"
        "- Other classes (pointSet, …) are not supported.\n\n"
        "Targets the OpenFOAM reader by default; pass `input_id` (from "
        "`get_pipeline`) if there is more than one reader. Returns the new "
        "source's `{id, name, type}`, `kind` (cellSet/faceSet), "
        "`num_in_set`, `num_cells_extracted`, and a `hint` if the counts "
        "disagree (a sign the mesh numbering does not match the set)."
    ),
    {
        "type": "object",
        "properties": {
            "set_name": {
                "type": "string",
                "description": (
                    "Set name as it appears under "
                    "`constant/polyMesh/sets/` (e.g. "
                    "'underdeterminedCells'). Omit any `.gz` suffix."
                ),
            },
            "input_id": {
                "type": "string",
                "description": (
                    "Optional OpenFOAMReader source id; defaults to the "
                    "reader in the pipeline."
                ),
            },
        },
        "required": ["set_name"],
    },
)
async def highlight_problem_cells(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/highlight_problem_cells", args)


# ── Display ────────────────────────────────────────────────────────────
@tool(
    "set_representation",
    (
        "Set how the active source is rendered: 'Surface', "
        "'Surface With Edges', 'Wireframe', 'Outline', 'Points', "
        "'Volume', 'Feature Edges'. Use 'Surface With Edges' to "
        "reveal mesh structure."
    ),
    {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["Surface", "Surface With Edges", "Wireframe",
                         "Outline", "Points", "Volume", "Feature Edges"],
            },
            "input_id": {"type": "string"},
        },
        "required": ["mode"],
    },
)
async def set_representation(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/set_representation", args)


@tool(
    "set_visibility",
    (
        "Show, hide, or toggle the active source's visibility in the "
        "active view."
    ),
    {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["show", "hide", "toggle"]},
            "input_id": {"type": "string"},
        },
        "required": ["mode"],
    },
)
async def set_visibility(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/set_visibility", args)


@tool(
    "set_opacity",
    (
        "Set surface opacity (0.0 transparent → 1.0 opaque). Pair a "
        "translucent outer hull (0.2) with an opaque clip/slice for a "
        "see-through view."
    ),
    {
        "type": "object",
        "properties": {
            "value": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "input_id": {"type": "string"},
        },
        "required": ["value"],
    },
)
async def set_opacity(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/set_opacity", args)


@tool(
    "color_by_array",
    (
        "Colour the active source by `array`. Auto-detects POINTS vs "
        "CELLS — OpenFOAM solver fields (U, p, T, k, omega, nut) live "
        "on CELLS. Pass `component` to colour by a single component "
        "of a vector array (0/1/2 for x/y/z); omit for magnitude. "
        "Rescales the transfer function and shows this array's colour "
        "legend. Legends for arrays no longer displayed by any visible "
        "source are dropped automatically, so the view never piles up "
        "stale bars (recolouring a source replaces its legend; to show "
        "two legends at once, colour two visible sources)."
    ),
    {
        "type": "object",
        "properties": {
            "array": {"type": "string"},
            "component": {"type": "integer"},
            "input_id": {"type": "string"},
        },
        "required": ["array"],
    },
)
async def color_by_array(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/color_by_array", args)


@tool(
    "set_solid_color",
    (
        "Switch off scalar colouring and set a solid RGB colour "
        "(components in [0, 1]). Also drops the source's colour legend, "
        "unless another visible source still uses that array."
    ),
    {
        "type": "object",
        "properties": {
            "rgb": {
                "type": "array",
                "items": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "minItems": 3,
                "maxItems": 3,
            },
            "input_id": {"type": "string"},
        },
        "required": ["rgb"],
    },
)
async def set_solid_color(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/set_solid_color", args)


@tool(
    "configure_colormap",
    (
        "Tune the colour transfer function for the array currently "
        "shown on the source (call `color_by_array` first). `preset` "
        "applies a named preset ('Cool to Warm', 'Viridis (matplotlib)', "
        "etc.); `range` clamps the scalar range; `rescale` rescales "
        "to data ('auto'), the visible range ('visible'), or across "
        "all timesteps ('all_timesteps'); `log` toggles log scaling."
    ),
    {
        "type": "object",
        "properties": {
            "preset": {"type": "string"},
            "range": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
            },
            "rescale": {
                "type": "string",
                "enum": ["auto", "visible", "all_timesteps"],
            },
            "log": {"type": "boolean"},
            "input_id": {"type": "string"},
        },
    },
)
async def configure_colormap(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/configure_colormap", args)


# ── OpenFOAM (write) ───────────────────────────────────────────────────
@tool(
    "set_openfoam_patches",
    (
        "Toggle which patches/regions the OpenFOAM reader has "
        "loaded. Pass lists of patch names to `enable` and/or "
        "`disable`. Re-reads the case after changing. Use "
        "`get_openfoam_patches` first to see what names are valid."
    ),
    {
        "type": "object",
        "properties": {
            "enable": {
                "type": "array",
                "items": {"type": "string"},
            },
            "disable": {
                "type": "array",
                "items": {"type": "string"},
            },
            "input_id": {"type": "string"},
        },
    },
)
async def set_openfoam_patches(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/set_openfoam_patches", args)


@tool(
    "set_read_zero_time",
    (
        "Toggle whether the OpenFOAM reader reads the `0/` time "
        "directory. The reader skips it by default, so fields written "
        "there are invisible — most importantly the mesh-quality fields "
        "from `checkMesh -writeAllFields` (skewness, nonOrthoAngle, "
        "cellAspectRatio, …), which land in `0/` for a mesh-only case. "
        "Set `enable: true` to read them, then `color_by_array`. "
        "Re-disable (`enable: false`) when inspecting solver results, "
        "since `0/` there is just the initial/boundary conditions, not "
        "a solution. Returns the arrays now loaded."
    ),
    {
        "type": "object",
        "properties": {
            "enable": {"type": "boolean"},
            "input_id": {"type": "string"},
        },
        "required": ["enable"],
    },
)
async def set_read_zero_time(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/set_read_zero_time", args)


# ── Camera / Time ──────────────────────────────────────────────────────
@tool(
    "set_camera",
    (
        "Move the active view's camera. Common patterns:\n"
        "- `preset`: axis ('+x', '-x', '+y', '-y', '+z', '-z'), "
        "iso-corner ('iso±x±y±z' — 8 variants, e.g. 'iso+x-y+z' = "
        "camera at [+1, -1, +1]), or 'reset'. For axis and iso "
        "variants the camera is placed AT the named direction "
        "looking back at the origin, then framed to fit all visible "
        "data (or a source(s) if `id` is supplied). 'reset' "
        "only re-frames at the current view direction without "
        "moving the camera.\n"
        "- `toward`: a vec3 (e.g. [0.7, 0.7, 0]) — looks toward that "
        "vector. Inverse of `preset` for axis-aligned cases. Mutually "
        "exclusive with `preset`.\n"
        "- `position`/`focal`/`up`: explicit camera placement.\n"
        "- `zoom`/`dolly`/`azimuth`/`elevation`/`roll`: incremental "
        "tweaks (multiplicative for zoom/dolly, degrees for the "
        "rotations).\n"
        "- `parallel`/`parallel_scale`: orthographic projection.\n"
        "- `patch`: an OpenFOAM patch/block name, or a list of them, to "
        "frame instead of a whole source. A list frames the combined "
        "bounds of all of them. Combine with `preset`/`toward` to orient "
        "then zoom onto just the patch(es), or pass alone to re-frame at "
        "the current angle. The patch must already be loaded: call "
        "`get_openfoam_patches` for the exact names (the full "
        "'patch/walls' or the bare leaf 'walls' both work) and "
        "`set_openfoam_patches` to load it first, else the call errors.\n\n"
        "Returns the updated camera state. Iterate by alternating "
        "`set_camera` and `save_screenshot`."
    ),
    {
        "type": "object",
        "properties": {
            "preset": {
                "type": "string",
                "enum": [
                    "+x", "-x", "+y", "-y", "+z", "-z",
                    "iso+x+y+z", "iso+x+y-z", "iso+x-y+z", "iso+x-y-z",
                    "iso-x+y+z", "iso-x+y-z", "iso-x-y+z", "iso-x-y-z",
                    "reset",
                ],
            },
            "toward": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
            "position": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
            "focal": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
            "up": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
            "zoom": {"type": "number"},
            "dolly": {"type": "number"},
            "azimuth": {"type": "number"},
            "elevation": {"type": "number"},
            "roll": {"type": "number"},
            "parallel": {"type": "boolean"},
            "parallel_scale": {"type": "number"},
            "id": {
                "type": "string",
                "description": (
                    "Source id to fit when used with `preset`/`toward` "
                    "— frames just that source instead of all visible. "
                    "With `patch`, selects which source to find the "
                    "patch in (defaults to the OpenFOAM reader)."
                ),
            },
            "patch": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
                "description": (
                    "OpenFOAM patch/block name (or list of names) to frame "
                    "instead of a whole source. A list frames their combined "
                    "bounds. Must be currently loaded."
                ),
            },
        },
    },
)
async def set_camera(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/set_camera", args)


@tool(
    "set_time",
    (
        "Move to a specific timestep. Pass exactly one of:\n"
        "- `t`: timestep value (must be in the available range; snaps "
        "to nearest available).\n"
        "- `step`: integer index into the available timesteps.\n"
        "- `move`: 'next' / 'prev' / 'first' / 'last'.\n"
        "Use `get_time` first to see what is available."
    ),
    {
        "type": "object",
        "properties": {
            "t": {"type": "number"},
            "step": {"type": "integer"},
            "move": {
                "type": "string",
                "enum": ["next", "prev", "first", "last"],
            },
        },
    },
)
async def set_time(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/set_time", args)


# ── Selection ──────────────────────────────────────────────────────────
@tool(
    "clear_selection",
    (
        "Clear the active source's interactive selection. Note that "
        "*creating* selections programmatically is not supported — "
        "the bridge can only read selections the user makes in the "
        "GUI. Use `apply_threshold_filter` / `apply_clip_filter` to "
        "subset by value or geometry instead."
    ),
    {
        "type": "object",
        "properties": {
            "input_id": {"type": "string"},
        },
    },
)
async def clear_selection(args: dict[str, Any]) -> dict[str, Any]:
    return await bridge_call("/clear_selection", args)


# Module-level list consumed by the package `__init__.py`. Order is
# stable so the agent's visible tool list is predictable.
WRITE_TOOLS = [
    ("load_dataset", load_dataset),
    ("create_geometry_source", create_geometry_source),
    ("set_active_source", set_active_source),
    ("set_active_view", set_active_view),
    ("delete_source", delete_source),
    ("apply_slice_filter", apply_slice_filter),
    ("apply_clip_filter", apply_clip_filter),
    ("apply_threshold_filter", apply_threshold_filter),
    ("apply_contour_filter", apply_contour_filter),
    ("apply_glyph_filter", apply_glyph_filter),
    ("apply_streamtracer_filter", apply_streamtracer_filter),
    ("apply_calculator_filter", apply_calculator_filter),
    ("compute_gradient_filter", compute_gradient_filter),
    ("extract_block", extract_block),
    ("extract_surface", extract_surface),
    ("extract_selection", extract_selection),
    ("highlight_problem_cells", highlight_problem_cells),
    ("set_representation", set_representation),
    ("set_visibility", set_visibility),
    ("set_opacity", set_opacity),
    ("color_by_array", color_by_array),
    ("set_solid_color", set_solid_color),
    ("configure_colormap", configure_colormap),
    ("set_openfoam_patches", set_openfoam_patches),
    ("set_read_zero_time", set_read_zero_time),
    ("set_camera", set_camera),
    ("set_time", set_time),
    ("clear_selection", clear_selection),
]
