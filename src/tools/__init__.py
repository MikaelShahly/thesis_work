"""Tool registry.

Two flavours of tool live behind one front door:

- Built-in Claude Code tools (WebSearch, Bash, Read, …) are referenced
  by their literal name.
- Custom Python tools live in one or more SDK MCP servers and are
  referenced as `mcp__<server>__<tool>`.

`build_tooling(tools, allowed_tools)` returns the
`(visible_tools, allowed_tools, mcp_servers)` triple that the agent
layer hands to ClaudeAgentOptions:

- `visible_tools` → ClaudeAgentOptions.tools (model's schema)
- `allowed_tools` → ClaudeAgentOptions.allowed_tools (auto-approve list)

`allowed_tools` is expected to be a subset of `tools`; entries in
`allowed_tools` that aren't also in `tools` are silently invisible to
the model.

Custom tools are partitioned by **server**, not flattened into one:
the existing `cfd` server hosts orchestration tools
(`present_specification`, `request_phase_advance`); the new `paraview`
server hosts every bridge verb plus `paraview_exec`. Per-tool routing
is encoded in `_CUSTOM_TOOLS` so adding a new server later is one
line, not a structural change.
"""

from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server

from src.tools.paraview import (
    PARAVIEW_MCP_SERVER_NAME,
    PARAVIEW_TOOL_OBJECTS,
)
from src.tools.quick_viz import (
    QUICK_VIZ_MCP_SERVER_NAME,
    QUICK_VIZ_TOOL,
    make_quick_viz,
)
from src.tools.paper_search import (
    PAPER_SEARCH_MCP_SERVER_NAME,
    paper_search,
)
from src.tools.web_fetch import (
    WEB_FETCH_MCP_SERVER_NAME,
    WEB_FETCH_TOOL,
    make_web_fetch,
)
from src.tools.present_spec import present_specification
from src.tools.request_experiment_approval import request_experiment_approval
from src.tools.request_mesh_approval import request_mesh_approval
from src.tools.request_phase_advance import request_phase_advance
from src.tools.request_subtask_approval import request_subtask_approval


CFD_MCP_SERVER_NAME = "cfd"

# Single source of truth: tool id (the name the phase config uses) →
# `(server_name, sdk_tool_object)`. Keep flat so the registry can't
# drift from the per-server breakdown.
_CUSTOM_TOOLS: dict[str, tuple[str, Any]] = {
    "present_specification": (CFD_MCP_SERVER_NAME, present_specification),
    "request_subtask_approval": (CFD_MCP_SERVER_NAME, request_subtask_approval),
    "request_experiment_approval": (
        CFD_MCP_SERVER_NAME, request_experiment_approval,
    ),
    "request_mesh_approval": (CFD_MCP_SERVER_NAME, request_mesh_approval),
    "request_phase_advance": (CFD_MCP_SERVER_NAME, request_phase_advance),
    # Static (no per-project binding, unlike web_fetch): hits public academic
    # APIs and returns candidates with direct OA pdf_urls for web_fetch to fetch.
    "paper_search": (PAPER_SEARCH_MCP_SERVER_NAME, paper_search),
    **{
        name: (PARAVIEW_MCP_SERVER_NAME, obj)
        for name, obj in PARAVIEW_TOOL_OBJECTS.items()
    },
}


# Some tool OBJECTS are built per turn (bound to the project dir), so they
# can't be static singletons in `_CUSTOM_TOOLS`:
#   - web_fetch  → bound to the project's .webcache dir
#   - quick_viz  → bound to the project dir (pvbatch's cwd, so config paths resolve)
# This map lets `translate_tool_names` still resolve their `mcp__<server>__<name>`
# form; `build_tooling` builds the bound object when a `project_dir` is supplied.
_DYNAMIC_TOOL_SERVERS: dict[str, str] = {
    WEB_FETCH_TOOL: WEB_FETCH_MCP_SERVER_NAME,
    QUICK_VIZ_TOOL: QUICK_VIZ_MCP_SERVER_NAME,
}


def translate_tool_names(names: list[str]) -> list[str]:
    """Translate raw tool names to the model-facing form.

    Custom tools registered in ``_CUSTOM_TOOLS`` get the
    ``mcp__<server>__<name>`` prefix; built-in tools (Bash, Read, …)
    pass through unchanged. Used by ``build_tooling`` for the
    parent's visible / allowed lists, and by ``build_subagents`` to
    populate ``AgentDefinition.tools`` (sub-agents reference tools
    by the same prefixed form the parent does).
    """
    out: list[str] = []
    for n in names:
        if n in _CUSTOM_TOOLS:
            server, _ = _CUSTOM_TOOLS[n]
            out.append(f"mcp__{server}__{n}")
        elif n in _DYNAMIC_TOOL_SERVERS:
            out.append(f"mcp__{_DYNAMIC_TOOL_SERVERS[n]}__{n}")
        else:
            out.append(n)
    return out


def build_tooling(
    tools: list[str],
    allowed_tools: list[str],
    extra_mcp_tools: list[str] | None = None,
    project_dir: Path | None = None,
) -> tuple[list[str], list[str], dict]:
    """Translate names and spin up the MCP servers the agent needs.

    ``tools`` / ``allowed_tools`` shape the parent's model-visible
    schema (what tools the parent sees, what auto-approves).

    ``extra_mcp_tools`` covers tools that **sub-agents** will call
    but the parent does not expose itself. The MCP server registry
    spins up tools listed in ``tools`` ∪ ``extra_mcp_tools``, but
    ``visible_tools`` / ``allowed_tools`` come from ``tools`` /
    ``allowed_tools`` only — so the parent doesn't gain a new tool
    in its schema just because a delegated sub-agent needs it. Bare
    names from ``extra_mcp_tools`` that aren't custom tools are
    ignored (built-ins don't need MCP registration).

    ``project_dir`` binds the per-turn ``web_fetch`` tool to that project's
    ``.webcache`` dir; omit it for phases that don't expose ``web_fetch``.
    """
    visible = translate_tool_names(tools)
    allowed = translate_tool_names(allowed_tools)

    # Union of every custom tool that should live in some MCP server,
    # de-duped by name so the same tool object isn't registered twice.
    union: list[str] = list(tools) + list(extra_mcp_tools or [])
    by_server: dict[str, list] = {}
    seen: set[str] = set()
    for n in union:
        if n in seen:
            continue
        seen.add(n)
        if n in _CUSTOM_TOOLS:
            server, obj = _CUSTOM_TOOLS[n]
            by_server.setdefault(server, []).append(obj)
        elif n == WEB_FETCH_TOOL and project_dir is not None:
            # Per-turn tool bound to this project's cache dir (plan §3): the
            # in-process @tool handler can't discover the project itself.
            obj = make_web_fetch(project_dir / ".webcache")
            by_server.setdefault(WEB_FETCH_MCP_SERVER_NAME, []).append(obj)
        elif n == QUICK_VIZ_TOOL and project_dir is not None:
            # Per-turn tool bound to the project dir — pvbatch runs there as
            # cwd so the config's relative paths resolve against the project
            # root. Same reason web_fetch is bound above.
            obj = make_quick_viz(project_dir)
            by_server.setdefault(QUICK_VIZ_MCP_SERVER_NAME, []).append(obj)

    mcp_servers: dict = {}
    for server, objs in by_server.items():
        mcp_servers[server] = create_sdk_mcp_server(name=server, tools=objs)

    return visible, allowed, mcp_servers
