"""The `paraview_exec` escape hatch tool.

Run arbitrary Python inside the live ParaView process. Sits outside
the read/write classification — phases opt in by name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

from src.tools.paraview._client import bridge_call


# The bridge runs `exec_script` on the GUI thread with a 10-minute
# timeout. Give the HTTP call a small extra margin so we hear the
# bridge's own timeout error rather than our own.
_EXEC_TIMEOUT_S = 660.0


@tool(
    "paraview_exec",
    (
        "Escape hatch: run arbitrary Python inside the live ParaView "
        "process. Prefer the dedicated verbs (load_dataset, "
        "apply_*_filter, set_camera, …) when one fits — `exec` "
        "produces less structured output and forces traceback reading "
        "if something breaks. However, using **`paraview_exec`** when it can significantly simplyfy your work and help you acheive your goals easier is completely fine and encouraged. \n\n"
        "Pass exactly one of:\n"
        "- `code`: inline Python string. For multi-statement scripts, "
        "assign the return value to `result` to surface it; for a "
        "single expression, the value is returned automatically.\n"
        "- `script_path`: filesystem path; the tool reads the file "
        "and runs its contents.\n\n"
        "Bound names already imported in the exec namespace: "
        "`paraview.simple.*` (everything from that module), "
        "`servermanager` (paraview.servermanager), and `vtk` "
        "(`vtkmodules.all`). No imports needed for those.\n\n"
        "CRASH WARNING (OpenFOAM data): `servermanager.Fetch(src)` "
        "followed by `GetTuple()` / `vtk_to_numpy()` on a multiblock "
        "OpenFOAM source can hard-segfault the whole ParaView process "
        "(the fetched arrays come back unreadable). To read field "
        "values, read the proxy's `GetPointDataInformation()` / "
        "`GetCellDataInformation()` `.GetArray(i).GetComponentRange(c)` "
        "— that is computed ParaView-side and never touches the corrupt "
        "memory. Avoid Fetch + per-element array access on OpenFOAM "
        "readers.\n\n"
        "Returns `{stdout, stderr, result, error}`. `error` carries a "
        "traceback string if the script raised; `result` is `repr()` "
        "of the value. The script runs on the GUI thread, blocking "
        "ParaView until it returns; per-call timeout is 10 minutes."
    ),
    {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Inline Python source.",
            },
            "script_path": {
                "type": "string",
                "description": (
                    "Path to a Python file. Mutually exclusive with "
                    "`code`."
                ),
            },
        },
    },
)
async def paraview_exec(args: dict[str, Any]) -> dict[str, Any]:
    code = args.get("code")
    script_path = args.get("script_path")
    if (code is None) == (script_path is None):
        return {
            "content": [{
                "type": "text",
                "text": (
                    "paraview_exec requires exactly one of `code` or "
                    "`script_path`."
                ),
            }],
            "is_error": True,
        }
    if script_path is not None:
        try:
            code = Path(script_path).read_text()
        except OSError as e:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Could not read script_path {script_path!r}: {e}",
                }],
                "is_error": True,
            }
    return await bridge_call("/exec", {"code": code}, timeout=_EXEC_TIMEOUT_S)
