"""Shape checks for the `paraview_operator` sub-agent.

These tests don't talk to the SDK or ParaView — they confirm the
registry entry, prompt file, and tool list are wired together the way
the mesh-agent phase will expect them.

Specifically:

- The registry entry exists and declares every key the SDK builder
  reads (`display_name`, `description`, `prompt_template`, `tools`,
  `model`).
- The `tools` list is **computed** from `PARAVIEW_READ_TOOLS` /
  `PARAVIEW_WRITE_TOOLS` / `PARAVIEW_EXEC_TOOL` — not duplicated as a
  literal — so adding a new bridge verb cannot drift the operator's
  surface from the actual tool registry.
- The prompt template file exists alongside the other prompts.
- `build_subagents(["paraview_operator"])` materialises a usable
  `AgentDefinition` (catches typos that would crash at phase startup).
"""

from claude_agent_sdk import AgentDefinition

from src.agent.subagents import build_subagents
from src.config import PROMPTS_DIR, SUBAGENT_REGISTRY
from src.tools.paraview import (
    PARAVIEW_EXEC_TOOL,
    PARAVIEW_READ_TOOLS,
    PARAVIEW_WRITE_TOOLS,
)


def test_paraview_operator_is_registered():
    assert "paraview_operator" in SUBAGENT_REGISTRY


def test_registry_entry_has_required_keys():
    cfg = SUBAGENT_REGISTRY["paraview_operator"]
    for key in ("display_name", "description", "prompt_template", "tools", "model"):
        assert key in cfg, f"missing key {key!r}"
    assert cfg["display_name"]
    assert cfg["description"]
    assert cfg["prompt_template"]
    assert cfg["tools"]
    assert cfg["model"]


def test_tools_cover_full_paraview_surface():
    # The plan pins this: the operator gets read + write verbs plus
    # the paraview_exec escape hatch. Anything missing here would
    # silently strip a capability from the operator's prompt-time
    # toolbelt.
    cfg = SUBAGENT_REGISTRY["paraview_operator"]
    expected = PARAVIEW_READ_TOOLS + PARAVIEW_WRITE_TOOLS + [PARAVIEW_EXEC_TOOL]
    assert cfg["tools"] == expected


def test_prompt_template_exists():
    cfg = SUBAGENT_REGISTRY["paraview_operator"]
    path = PROMPTS_DIR / cfg["prompt_template"]
    assert path.is_file(), f"prompt template missing at {path}"
    assert path.read_text().strip(), "prompt template is empty"


def test_build_subagents_materialises_agent_definition():
    # If the registry entry references a missing prompt, a missing
    # tool, or anything else that the SDK builder would fail on, this
    # test surfaces it at import / unit-test time rather than at the
    # first mesh-phase invocation.
    agents, tool_union = build_subagents(["paraview_operator"])
    assert agents is not None
    assert "paraview_operator" in agents
    defn = agents["paraview_operator"]
    assert isinstance(defn, AgentDefinition)
    assert defn.description
    assert defn.prompt
    assert defn.tools
    # Tool union mirrors the registry list (de-duped, order preserved)
    # so the mesh phase can pass it to build_tooling as extra_mcp_tools.
    expected = SUBAGENT_REGISTRY["paraview_operator"]["tools"]
    assert tool_union == expected


def test_subagent_tools_are_mcp_prefixed():
    # AgentDefinition.tools must carry the model-facing form —
    # `mcp__paraview__<verb>` for MCP tools. The earlier wiring bug
    # (passing raw names) made the sub-agent see zero tools and
    # hallucinate XML-style tool calls in its reply; this test pins
    # the translation in place.
    agents, _ = build_subagents(["paraview_operator"])
    assert agents is not None
    tools = agents["paraview_operator"].tools or []
    # Every paraview verb should land prefixed; nothing should be a
    # bare name.
    assert all(t.startswith("mcp__paraview__") for t in tools), (
        f"un-prefixed tools in sub-agent definition: {tools}"
    )
