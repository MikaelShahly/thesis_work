"""Shape checks for `PHASE_CONFIGS["mesh"]`.

These tests don't exercise the SDK or run any meshing utility — they
confirm the mesh phase is *wired* the way the plan §5.1 specifies:

- Every required key is present and well-typed.
- The tool list includes the new approval tools, the ParaView read
  surface, `paraview_exec`, and `WebSearch`.
- `Bash` and `paraview_exec` are visible to the agent but NOT
  auto-approved — both must route through `can_use_tool` per call.
- `build_tooling()` resolves every tool name (catches typos that
  would otherwise crash at phase startup) and the subagent list
  materialises into valid AgentDefinitions with MCP-prefixed tool
  names.
- The handler module imports cleanly and registers under
  `PHASE_HANDLERS`.
"""

from claude_agent_sdk import AgentDefinition

from src.agent.subagents import build_subagents
from src.config import PHASE_CONFIGS
from src.tools import build_tooling
from src.tools.paraview import (
    PARAVIEW_EXEC_TOOL,
    PARAVIEW_READ_TOOLS,
    PARAVIEW_WRITE_TOOLS,
)


def test_mesh_phase_registered():
    assert "mesh" in PHASE_CONFIGS


def test_required_keys_present():
    cfg = PHASE_CONFIGS["mesh"]
    for key in (
        "model", "prompt_template", "tools", "allowed_tools",
        "permission_mode", "max_turns", "subagents",
    ):
        assert key in cfg, f"missing key {key!r}"


def test_tool_list_covers_read_surface_plus_approval_tools():
    cfg = PHASE_CONFIGS["mesh"]
    tools = cfg["tools"]

    # Built-in dev tools the mesh agent needs.
    for builtin in ("Read", "Write", "Edit", "Glob", "Grep", "Bash",
                    "Agent", "WebSearch"):
        assert builtin in tools, f"missing built-in tool: {builtin}"

    # Every ParaView read verb is exposed.
    for verb in PARAVIEW_READ_TOOLS:
        assert verb in tools, f"missing ParaView read verb: {verb}"

    # The exec escape hatch is exposed (gated, not auto-approved).
    assert PARAVIEW_EXEC_TOOL in tools

    # The new approval tools.
    assert "request_subtask_approval" in tools
    assert "request_phase_advance" in tools


def test_paraview_write_verbs_not_in_mesh_phase_tools():
    # The mesh agent itself does not mutate the user's ParaView scene
    # — that's the operator sub-agent's job. Including write verbs in
    # the parent's `tools` would let the model bypass delegation.
    cfg = PHASE_CONFIGS["mesh"]
    tools = set(cfg["tools"])
    leaks = [v for v in PARAVIEW_WRITE_TOOLS if v in tools]
    assert not leaks, f"mesh phase exposes ParaView write verbs: {leaks}"


def test_bash_and_paraview_exec_are_gated():
    # Both must be in `tools` (visible to the model) but NOT in
    # `allowed_tools` (auto-approved) — every call routes through
    # can_use_tool.
    cfg = PHASE_CONFIGS["mesh"]
    assert "Bash" in cfg["tools"]
    assert "Bash" not in cfg["allowed_tools"]
    assert PARAVIEW_EXEC_TOOL in cfg["tools"]
    assert PARAVIEW_EXEC_TOOL not in cfg["allowed_tools"]


def test_approval_tools_are_auto_approved():
    cfg = PHASE_CONFIGS["mesh"]
    # The approval tools take no arguments and have no side effects
    # the user needs to vet — they just surface a UI prompt. Gating
    # them per call would force the user to approve the act of being
    # asked, which is absurd.
    assert "request_subtask_approval" in cfg["allowed_tools"]
    assert "request_phase_advance" in cfg["allowed_tools"]


def test_subagents_include_explorer_and_operator():
    cfg = PHASE_CONFIGS["mesh"]
    assert cfg["subagents"] == [
        "openfoam2412_repository_explore",
        "paraview_operator",
    ]


def test_build_tooling_resolves_without_error():
    # Any typo in the tool list — e.g. `request_phase_advanc` —
    # crashes here with a translation that quietly drops the entry.
    # Asserting on the visible_tools shape catches that.
    cfg = PHASE_CONFIGS["mesh"]
    _, tool_union = build_subagents(cfg["subagents"])
    visible, allowed, mcp_servers = build_tooling(
        cfg["tools"], cfg["allowed_tools"], extra_mcp_tools=tool_union,
    )
    # Custom tools land prefixed; built-ins pass through.
    assert "mcp__cfd__request_subtask_approval" in visible
    assert "mcp__cfd__request_phase_advance" in visible
    assert "Bash" in visible
    # MCP servers spin up for cfd + paraview (operator adds the write
    # surface via extra_mcp_tools).
    assert "cfd" in mcp_servers
    assert "paraview" in mcp_servers


def test_build_subagents_yields_valid_agent_definitions():
    cfg = PHASE_CONFIGS["mesh"]
    agents, tool_union = build_subagents(cfg["subagents"])
    assert agents is not None
    assert "openfoam2412_repository_explore" in agents
    assert "paraview_operator" in agents
    for name, defn in agents.items():
        assert isinstance(defn, AgentDefinition), name
        assert defn.tools, f"subagent {name!r} has empty tool list"

    # Every MCP-bound sub-agent tool must arrive with the
    # `mcp__<server>__<verb>` prefix or the SDK silently drops it
    # (the phase-4 bug). Built-ins (Bash, Read, Glob, Grep) pass
    # through bare for the explorer.
    operator_tools = agents["paraview_operator"].tools or []
    assert all(t.startswith("mcp__paraview__") for t in operator_tools), (
        f"un-prefixed operator tools: {operator_tools}"
    )

    # The tool union from build_subagents covers the operator's surface
    # (used by build_tooling as extra_mcp_tools so the operator's writes
    # are registered even though the parent doesn't expose them).
    for verb in PARAVIEW_WRITE_TOOLS:
        assert verb in tool_union, f"operator surface missing in union: {verb}"


def test_mesh_handler_registered():
    # Late import — routes.py pulls in run_mesh_turn at module level,
    # so a typo in the handler import would prevent the whole app from
    # starting.
    from src.api.routes import PHASE_HANDLERS

    assert "mesh" in PHASE_HANDLERS
    handler = PHASE_HANDLERS["mesh"]
    # Async generator handler — at this layer the type check is just
    # "it's callable and we got the right thing."
    assert callable(handler)
    assert handler.__name__ == "run_mesh_turn"


def test_mesh_prompt_template_exists():
    cfg = PHASE_CONFIGS["mesh"]
    from src.config import PROMPTS_DIR

    path = PROMPTS_DIR / cfg["prompt_template"]
    assert path.is_file(), f"prompt template missing at {path}"
    body = path.read_text()
    # The three placeholders the handler formats — drift here would
    # crash at the first mesh turn with a KeyError from str.format.
    assert "{simulation_specification}" in body
    assert "{openfoam_source_dir}" in body
    assert "{geometry_dir}" in body
