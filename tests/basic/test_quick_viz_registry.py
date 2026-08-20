"""Registration wiring for the quick_viz tool (no ParaView needed).

quick_viz is a per-turn, project-bound tool (like web_fetch), so:

- it resolves to ``mcp__quick_viz__quick_viz`` through the registry,
- ``build_tooling`` only spins up its server when a ``project_dir`` is
  supplied (the bound object needs the project dir to set pvbatch's cwd),
- it reaches the ``cfd_general_purpose`` sub-agent via the
  ``extra_mcp_tools`` union without entering the parent's schema,
- the mesh phase both exposes and auto-approves it.
"""

from src.config import PHASE_CONFIGS, SUBAGENT_REGISTRY
from src.tools import build_tooling, translate_tool_names
from src.tools.quick_viz import QUICK_VIZ_MCP_SERVER_NAME, QUICK_VIZ_TOOL


_MCP_NAME = f"mcp__{QUICK_VIZ_MCP_SERVER_NAME}__{QUICK_VIZ_TOOL}"


def test_translates_to_mcp_name():
    assert translate_tool_names([QUICK_VIZ_TOOL]) == [_MCP_NAME]


def test_server_created_only_with_project_dir(tmp_path):
    # No project_dir: the name still resolves in the visible list, but the
    # bound object can't be built, so no server is created.
    visible, _allowed, mcp = build_tooling([QUICK_VIZ_TOOL], [QUICK_VIZ_TOOL])
    assert visible == [_MCP_NAME]
    assert QUICK_VIZ_MCP_SERVER_NAME not in mcp

    # With project_dir the server spins up.
    _v, _a, mcp2 = build_tooling(
        [QUICK_VIZ_TOOL], [QUICK_VIZ_TOOL], project_dir=tmp_path
    )
    assert QUICK_VIZ_MCP_SERVER_NAME in mcp2


def test_reachable_via_subagent_union_only(tmp_path):
    # Parent exposes only Read; a sub-agent needs quick_viz (extra_mcp_tools).
    # The server must spin up, but the tool stays out of the parent's schema.
    visible, _allowed, mcp = build_tooling(
        ["Read"], ["Read"],
        extra_mcp_tools=[QUICK_VIZ_TOOL],
        project_dir=tmp_path,
    )
    assert _MCP_NAME not in visible
    assert QUICK_VIZ_MCP_SERVER_NAME in mcp


def test_mesh_phase_exposes_and_autoapproves():
    assert QUICK_VIZ_TOOL in PHASE_CONFIGS["mesh"]["tools"]
    assert QUICK_VIZ_TOOL in PHASE_CONFIGS["mesh"]["allowed_tools"]


def test_cfd_general_purpose_subagent_has_it():
    assert QUICK_VIZ_TOOL in SUBAGENT_REGISTRY["cfd_general_purpose"]["tools"]
