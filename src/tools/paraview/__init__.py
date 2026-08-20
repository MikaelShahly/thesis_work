"""ParaView tool surface.

Three modules under this package:

- `read_paraview_state.py` — verbs that observe state (no mutation).
- `change_paraview_state.py` — verbs that mutate state.
- `exec_tool.py` — `paraview_exec`, the escape hatch (separate from
  read/write so phases opt in by name).

The classification is the file layout. `PARAVIEW_READ_TOOLS` /
`PARAVIEW_WRITE_TOOLS` are derived from each module's `READ_TOOLS` /
`WRITE_TOOLS` list and exported here for phase configs to compose.
The shared `PARAVIEW_TOOL_OBJECTS` dict (id → SDK tool) is consumed
by `src/tools/__init__.py` when it builds the `paraview` MCP server.

`PARAVIEW_MCP_SERVER_NAME` is the MCP server these tools register
against — visible to the model as `mcp__paraview__<verb>`.
"""

from src.tools.paraview.change_paraview_state import WRITE_TOOLS as _WRITE
from src.tools.paraview.exec_tool import paraview_exec
from src.tools.paraview.launch_tool import launch_paraview
from src.tools.paraview.read_paraview_state import READ_TOOLS as _READ


PARAVIEW_MCP_SERVER_NAME = "paraview"

PARAVIEW_READ_TOOLS = [name for name, _ in _READ]
PARAVIEW_WRITE_TOOLS = [name for name, _ in _WRITE]
PARAVIEW_EXEC_TOOL = "paraview_exec"
# Lifecycle verb: spawns the ParaView process (vs. the read/write/exec
# verbs that talk to an already-running bridge). Kept as its own
# constant so phases opt in by name and it doesn't flow into the
# sub-agent tool surfaces computed from READ/WRITE.
PARAVIEW_LAUNCH_TOOL = "launch_paraview"

PARAVIEW_TOOL_OBJECTS: dict = {
    **{name: tool_obj for name, tool_obj in _READ},
    **{name: tool_obj for name, tool_obj in _WRITE},
    PARAVIEW_EXEC_TOOL: paraview_exec,
    PARAVIEW_LAUNCH_TOOL: launch_paraview,
}


__all__ = [
    "PARAVIEW_MCP_SERVER_NAME",
    "PARAVIEW_READ_TOOLS",
    "PARAVIEW_WRITE_TOOLS",
    "PARAVIEW_EXEC_TOOL",
    "PARAVIEW_LAUNCH_TOOL",
    "PARAVIEW_TOOL_OBJECTS",
]
