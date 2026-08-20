"""Layout sanity for the ParaView tool surface.

Confirms each module under `src/tools/paraview/` exports the
`@tool`-decorated callables it declares, that importing the
subpackage doesn't raise (no accidental ParaView/VTK imports), and
that the read/write classification is consistent with the file each
tool lives in.

This is purely structural — it does not call the bridge.
"""

from claude_agent_sdk import tool as _tool_decorator  # noqa: F401  (smoke import)

from src.tools.paraview import (
    PARAVIEW_EXEC_TOOL,
    PARAVIEW_MCP_SERVER_NAME,
    PARAVIEW_READ_TOOLS,
    PARAVIEW_TOOL_OBJECTS,
    PARAVIEW_WRITE_TOOLS,
)
from src.tools.paraview import change_paraview_state, exec_tool, read_paraview_state


def test_subpackage_imports_cleanly():
    # No-op assertion — the import statements above must not raise.
    # If `read_paraview_state` accidentally pulled in `paraview.simple`
    # or VTK at import time, this would have failed before reaching us.
    assert PARAVIEW_MCP_SERVER_NAME == "paraview"


def test_read_module_exports_match_constant():
    # Names listed in PARAVIEW_READ_TOOLS must correspond 1:1 with the
    # READ_TOOLS list inside `read_paraview_state.py`.
    declared = [name for name, _ in read_paraview_state.READ_TOOLS]
    assert declared == PARAVIEW_READ_TOOLS


def test_write_module_exports_match_constant():
    declared = [name for name, _ in change_paraview_state.WRITE_TOOLS]
    assert declared == PARAVIEW_WRITE_TOOLS


def test_exec_tool_lives_outside_read_and_write():
    # paraview_exec is its own opt-in name — phases must add it
    # explicitly. Mixing it into either list would silently grant the
    # escape hatch wherever read or write tools land.
    assert PARAVIEW_EXEC_TOOL == "paraview_exec"
    assert PARAVIEW_EXEC_TOOL not in PARAVIEW_READ_TOOLS
    assert PARAVIEW_EXEC_TOOL not in PARAVIEW_WRITE_TOOLS
    assert exec_tool.paraview_exec.name == PARAVIEW_EXEC_TOOL


def test_tool_objects_dict_covers_everything():
    expected = set(PARAVIEW_READ_TOOLS) | set(PARAVIEW_WRITE_TOOLS) | {PARAVIEW_EXEC_TOOL}
    assert set(PARAVIEW_TOOL_OBJECTS.keys()) == expected
    # Every value is an SdkMcpTool with `.name` matching its key.
    for key, obj in PARAVIEW_TOOL_OBJECTS.items():
        assert obj.name == key
        assert obj.description  # non-empty
        assert isinstance(obj.input_schema, dict)


def test_no_overlap_between_read_and_write():
    # If a verb shows up in both lists the file-layout-as-classification
    # invariant is broken.
    overlap = set(PARAVIEW_READ_TOOLS) & set(PARAVIEW_WRITE_TOOLS)
    assert not overlap, f"read/write overlap: {overlap}"


def test_export_snapshot_is_not_exposed_to_the_agent():
    # The bridge endpoint /export_snapshot stays so the frontend can
    # later POST to it for a "send current ParaView state to the
    # LLM" flow. But the agent itself must not call it — that route
    # is user-driven, not agent-driven. Defensive: anything bringing
    # the verb back into READ/WRITE/EXEC will trip this test.
    all_visible = set(PARAVIEW_READ_TOOLS) | set(PARAVIEW_WRITE_TOOLS) | {PARAVIEW_EXEC_TOOL}
    assert "export_snapshot" not in all_visible
    assert "export_snapshot" not in PARAVIEW_TOOL_OBJECTS
