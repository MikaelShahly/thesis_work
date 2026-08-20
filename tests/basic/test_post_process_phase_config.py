"""Shape checks for `PHASE_CONFIGS["post_process"]` and its handler.

No SDK calls / no skill execution — these confirm the post_process
phase is *wired* the way the implementation plan specifies:

- Required keys present and well-typed, including `skills` and
  `subagents`.
- The tool surface covers the dev tools the skills need (Bash for
  pyvista/pandoc/latex builds, Glob/Grep), AskUserQuestion (Stage 1),
  WebSearch + WebFetch, the `Skill` tool, the ParaView read surface,
  and `paraview_exec`.
- `Bash` and `paraview_exec` are visible but NOT auto-approved.
- `build_tooling()` resolves every tool name and spins up the cfd +
  paraview MCP servers; the cfd_general_purpose sub-agent materialises.
- The prompt substitutes `{project_dir}` only (no stray placeholders),
  and points at the real on-disk paths.
- The handler imports cleanly and registers under PHASE_HANDLERS,
  forwarding `skills` into run_turn.
"""

import inspect

from claude_agent_sdk import AgentDefinition

from src.agent.subagents import build_subagents
from src.config import PHASE_CONFIGS, PROMPTS_DIR
from src.tools import build_tooling
from src.tools.paraview import (
    PARAVIEW_EXEC_TOOL,
    PARAVIEW_READ_TOOLS,
    PARAVIEW_WRITE_TOOLS,
)


def test_post_process_phase_registered():
    assert "post_process" in PHASE_CONFIGS


def test_required_keys_present():
    cfg = PHASE_CONFIGS["post_process"]
    for key in (
        "model", "prompt_template", "tools", "allowed_tools",
        "permission_mode", "max_turns", "skills", "subagents",
    ):
        assert key in cfg, f"missing key {key!r}"


def test_tool_surface_covers_skill_build_needs():
    cfg = PHASE_CONFIGS["post_process"]
    tools = cfg["tools"]

    # Dev tools the skills + figure/report builds need.
    for builtin in ("Read", "Write", "Edit", "Glob", "Grep", "Bash",
                    "Agent", "WebSearch", "WebFetch", "AskUserQuestion",
                    "Skill"):
        assert builtin in tools, f"missing built-in tool: {builtin}"

    # ParaView read surface + exec (for ParaView-based figures when the
    # user asks for them).
    for verb in PARAVIEW_READ_TOOLS:
        assert verb in tools, f"missing ParaView read verb: {verb}"
    assert PARAVIEW_EXEC_TOOL in tools


def test_paraview_write_verbs_not_exposed():
    # ParaView mutation is delegated; the parent only reads + exec.
    cfg = PHASE_CONFIGS["post_process"]
    tools = set(cfg["tools"])
    leaks = [v for v in PARAVIEW_WRITE_TOOLS if v in tools]
    assert not leaks, f"post_process exposes ParaView write verbs: {leaks}"


def test_bash_and_paraview_exec_are_gated():
    cfg = PHASE_CONFIGS["post_process"]
    assert "Bash" in cfg["tools"]
    assert "Bash" not in cfg["allowed_tools"]
    assert PARAVIEW_EXEC_TOOL in cfg["tools"]
    assert PARAVIEW_EXEC_TOOL not in cfg["allowed_tools"]


def test_skills_grant_is_the_three_report_skills():
    cfg = PHASE_CONFIGS["post_process"]
    assert set(cfg["skills"]) == {"latex-report", "html-report", "visualization"}


def test_subagents_is_cfd_general_purpose():
    cfg = PHASE_CONFIGS["post_process"]
    assert cfg["subagents"] == ["cfd_general_purpose"]


def test_build_tooling_resolves_without_error():
    cfg = PHASE_CONFIGS["post_process"]
    _, tool_union = build_subagents(cfg["subagents"])
    visible, allowed, mcp_servers = build_tooling(
        cfg["tools"], cfg["allowed_tools"], extra_mcp_tools=tool_union,
    )
    # Built-ins pass through bare; ParaView verbs land MCP-prefixed.
    assert "Bash" in visible
    assert "Skill" in visible
    assert "AskUserQuestion" in visible
    assert "mcp__paraview__paraview_exec" in visible
    # MCP servers spin up for cfd (sub-agent surface) + paraview.
    assert "paraview" in mcp_servers


def test_build_subagents_yields_valid_definition():
    cfg = PHASE_CONFIGS["post_process"]
    agents, _ = build_subagents(cfg["subagents"])
    assert agents is not None
    assert "cfd_general_purpose" in agents
    defn = agents["cfd_general_purpose"]
    assert isinstance(defn, AgentDefinition)
    assert defn.tools, "cfd_general_purpose has empty tool list"


def test_prompt_template_substitutes_project_dir_only():
    cfg = PHASE_CONFIGS["post_process"]
    path = PROMPTS_DIR / cfg["prompt_template"]
    assert path.is_file(), f"prompt template missing at {path}"
    body = path.read_text()
    # The handler formats with project_dir only — any other {placeholder}
    # would crash with a KeyError at the first turn.
    import re
    placeholders = set(re.findall(r"\{([a-zA-Z0-9_]+)\}", body))
    assert placeholders == {"project_dir"}, (
        f"unexpected placeholders in prompt: {placeholders}"
    )

    from src.phases.post_process import build_system_prompt
    rendered = build_system_prompt("/abs/projX")
    assert "{project_dir}" not in rendered
    # Real on-disk paths, not the old project-root-relative bug.
    assert "/abs/projX/Specification/simulation_specification.md" in rendered
    assert "/abs/projX/handoffs/improver_agent.md" in rendered
    assert "/abs/projX/Reports" in rendered


def test_post_process_handler_registered_and_forwards_skills():
    from src.api.routes import PHASE_HANDLERS

    assert "post_process" in PHASE_HANDLERS
    handler = PHASE_HANDLERS["post_process"]
    assert callable(handler)
    assert handler.__name__ == "run_post_process_turn"

    # The handler must forward `skills` into run_turn — the one thing
    # that injects the Skill tool. Cheapest reliable check without an
    # SDK round-trip: the source threads skills through.
    src = inspect.getsource(handler)
    assert "skills=" in src, "handler does not forward skills= to run_turn"
