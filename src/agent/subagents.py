"""Materialise sub-agent definitions for ClaudeAgentOptions.agents.

A phase declares the sub-agents it wants by NAME (a list of keys into
``SUBAGENT_REGISTRY`` in ``src.config``); ``build_subagents()`` reads
the registry, loads + substitutes the prompt template, translates
tool names into the model-facing form, and returns:

1. ``{name: AgentDefinition}`` — the dict the SDK expects for
   ``ClaudeAgentOptions.agents``.
2. The **MCP tool union** — every custom tool any sub-agent in
   ``names`` might call. Pass this to
   ``build_tooling(..., extra_mcp_tools=...)`` so the MCP servers
   register tools the sub-agent needs but the parent doesn't expose
   in its own schema (e.g. the operator's write verbs).

Defining each sub-agent once in the registry — and referencing it by
name from any phase that needs it — keeps the phase config
declarative and avoids duplicated prompt/tool lists.
"""

from __future__ import annotations

from claude_agent_sdk import AgentDefinition

from src.config import OPENFOAM_SOURCE_DIR, PROMPTS_DIR, SUBAGENT_REGISTRY
from src.tools import translate_tool_names


def build_subagents(
    names: list[str] | None,
    project_dir: str | None = None,
) -> tuple[dict[str, AgentDefinition] | None, list[str]]:
    """Build the ``agents=`` dict + the MCP tool union for a phase.

    Returns ``(agents_or_None, tool_union)``:

    - ``agents_or_None`` is the dict the caller passes straight into
      ``ClaudeAgentOptions.agents``. ``None`` (rather than ``{}``)
      when there are no sub-agents — the SDK treats ``None`` as "no
      sub-agent delegation".
    - ``tool_union`` is the de-duped list of every tool any
      sub-agent in ``names`` declares. Pass it to
      ``build_tooling(..., extra_mcp_tools=...)`` so the MCP server
      registry has those tools available for the sub-agent to call,
      even when the parent omits them.

    ``project_dir`` is substituted into sub-agent prompts that
    reference ``{project_dir}``. Sub-agents inherit ``cwd`` from
    the parent agent, but the parent may `cd` away in a Bash call —
    so prompts that need to refer to the project root use the
    absolute path baked in here rather than relying on cwd.
    Sub-agent prompts that don't reference the placeholder are
    unaffected; callers that don't have a project_dir handy can
    leave it ``None``.

    Unknown names raise ``KeyError`` so a typo in PHASE_CONFIGS
    surfaces at startup rather than silently dropping a sub-agent.
    """
    if not names:
        return None, []
    out: dict[str, AgentDefinition] = {}
    union_seen: set[str] = set()
    tool_union: list[str] = []
    for name in names:
        cfg = SUBAGENT_REGISTRY[name]
        # Plain .replace() rather than .format() — the explore prompt's
        # OpenFOAM orientation block contains literal `{ … }` braces
        # that str.format would misread as positional placeholders.
        prompt = (
            (PROMPTS_DIR / cfg["prompt_template"])
            .read_text()
            .replace("{openfoam_source_dir}", OPENFOAM_SOURCE_DIR)
        )
        if project_dir is not None:
            prompt = prompt.replace("{project_dir}", project_dir)
        raw_tools = cfg.get("tools") or []
        for t in raw_tools:
            if t in union_seen:
                continue
            union_seen.add(t)
            tool_union.append(t)
        out[name] = AgentDefinition(
            description=cfg["description"],
            prompt=prompt,
            # AgentDefinition.tools wants model-facing names — same
            # prefixed form (`mcp__<server>__<verb>`) the parent's
            # tool list uses. Without this, MCP tools listed by raw
            # name are silently dropped at SDK level and the
            # sub-agent runs with no ParaView surface.
            tools=translate_tool_names(raw_tools),
            model=cfg.get("model"),
            effort=cfg.get("effort"),
        )
    return out, tool_union
