"""Schema sanity for ParaView tools through the central registry.

`build_tooling()` is the only public entry point into the tooling
layer. Each ParaView tool listed must:

- Resolve through `build_tooling()` and land in the visible-tool list
  as `mcp__paraview__<verb>` (the model-facing reference shape).
- Cause the `paraview` MCP server to be created — and only it (no
  spurious `cfd` server creation when no cfd tools were requested).
"""

from src.tools import build_tooling
from src.tools.paraview import (
    PARAVIEW_EXEC_TOOL,
    PARAVIEW_MCP_SERVER_NAME,
    PARAVIEW_READ_TOOLS,
    PARAVIEW_WRITE_TOOLS,
)


_ALL_PARAVIEW = list(PARAVIEW_READ_TOOLS) + list(PARAVIEW_WRITE_TOOLS) + [PARAVIEW_EXEC_TOOL]


def test_every_paraview_tool_resolves_under_paraview_server():
    visible, _allowed, _mcp = build_tooling(_ALL_PARAVIEW, _ALL_PARAVIEW)
    expected = [f"mcp__{PARAVIEW_MCP_SERVER_NAME}__{n}" for n in _ALL_PARAVIEW]
    assert visible == expected


def test_paraview_server_is_created_when_paraview_tools_requested():
    # Only paraview tools requested — there should be exactly one MCP
    # server in the dict, named "paraview". The cfd server must not
    # spin up just because it exists in the registry.
    _visible, _allowed, mcp = build_tooling(_ALL_PARAVIEW, _ALL_PARAVIEW)
    assert list(mcp.keys()) == [PARAVIEW_MCP_SERVER_NAME]


def test_cfd_and_paraview_servers_coexist():
    # If a phase mixes cfd-server and paraview-server tools (the mesh
    # phase will), build_tooling must create both servers and route
    # the visible names to the right prefix.
    requested = ["request_phase_advance"] + PARAVIEW_READ_TOOLS
    visible, _allowed, mcp = build_tooling(requested, requested)

    assert {"cfd", PARAVIEW_MCP_SERVER_NAME} == set(mcp.keys())
    assert "mcp__cfd__request_phase_advance" in visible
    for n in PARAVIEW_READ_TOOLS:
        assert f"mcp__paraview__{n}" in visible


def test_builtin_tools_pass_through_unchanged():
    # Non-custom tool names (Bash, Read, …) keep their literal name —
    # they are not part of any MCP server.
    visible, _allowed, _mcp = build_tooling(["Bash", "Read", "ping"], ["Read", "ping"])
    assert visible[:2] == ["Bash", "Read"]
    assert visible[2] == f"mcp__{PARAVIEW_MCP_SERVER_NAME}__ping"


def test_paraview_exec_routes_through_paraview_server():
    visible, _allowed, mcp = build_tooling([PARAVIEW_EXEC_TOOL], [PARAVIEW_EXEC_TOOL])
    assert visible == [f"mcp__{PARAVIEW_MCP_SERVER_NAME}__{PARAVIEW_EXEC_TOOL}"]
    assert list(mcp.keys()) == [PARAVIEW_MCP_SERVER_NAME]
