"""Central configuration.

Paths, server settings, and the phase registry. The Agent SDK owns
context management, so each phase only needs a model, a prompt
template, and the list of tools it's allowed to use.
"""

from pathlib import Path

from src.tools.paraview import (
    PARAVIEW_EXEC_TOOL,
    PARAVIEW_LAUNCH_TOOL,
    PARAVIEW_READ_TOOLS,
    PARAVIEW_WRITE_TOOLS,
)


# ── Paths ──
PROJECT_ROOT = Path(__file__).parent.parent
PROJECTS_DIR = PROJECT_ROOT / "projects"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
DB_PATH = PROJECT_ROOT / "data" / "agenticcfd.db"

# Root of the OpenFOAM 2412 source tree (contains src/, applications/,
# tutorials/, …). Substituted into the case_builder system prompt so
# the agent can navigate the source for syntax/tutorial lookups.
OPENFOAM_SOURCE_DIR = "/usr/lib/openfoam/openfoam2412"

# Curated snappyHexMesh troubleshooting/advice KB that ships with the
# repo (start at INDEX.md). Substituted into the mesh and improver
# prompts so those agents can consult it when meshing gets stuck.
MESH_ADVICE_DIR = str(PROJECT_ROOT / "snappyHexMeshAdvice")

# cfMesh worked tutorials that ship with the repo. Substituted into the
# mesh and improver prompts so those agents can consult them.
CFMESH_TUTORIALS_DIR = str(PROJECT_ROOT / "cfMesh_tutorials")


# ── Server ──
HOST = "127.0.0.1"
PORT = 8000
FRONTEND_ORIGIN = "http://localhost:5173"


# ── Geometry uploads ──
# Extensions accepted by POST /projects/{id}/geometry. Anything else is
# rejected with 415. The list spans the OpenFOAM-friendly surface: STL
# variants, common point/triangle meshes, and CAD interchange formats
# (step/iges) that the user might pre-process downstream. Match by
# lowercased suffix; the backend lower-cases before comparing.
GEOMETRY_EXTENSIONS = frozenset({
    ".stl", ".obj", ".ply", ".vtk", ".nas",
    ".ftr", ".off", ".x3d", ".step", ".stp",
    ".iges", ".igs",
})

# Per-file size cap for geometry uploads. The backend stream-writes in
# 1 MiB chunks and aborts mid-write past this; the partial file is
# unlinked. 5 GiB is generous — the UX assumption is "the user is not
# uploading absurd files," not bullet-proof multi-GB ingestion.
MAX_GEOMETRY_SIZE_BYTES = 5 * 1024 * 1024 * 1024


# ── Sub-agent registry ──
# Single source of truth for every programmatic sub-agent the project
# can spawn. Phases reference entries by name (the dict key) via their
# own `subagents` list; the builder in src/agent/subagents.py
# materialises these into claude_agent_sdk.AgentDefinition instances.
#
# The dict key is what the parent passes as `subagent_type` when it
# invokes the `Agent` tool, what the SDK reports as `agent_id` on
# ToolPermissionContext, and what the frontend's
# SUBAGENT_DISPLAY_NAMES map keys on — keep all three in sync.
#
# Per-entry keys:
#   display_name    — human label surfaced to the UI as the sub-agent
#                     prefix on chat / permission rows. (Frontend has
#                     its own copy keyed by the same name.)
#   description     — selection hint shown to the parent model; controls
#                     when it delegates. The parent sees this verbatim,
#                     so write it as guidance, not internal docs.
#   prompt_template — file in prompts/, substituted via plain .replace()
#                     for {openfoam_source_dir} (str.format would choke
#                     on the literal `{ … }` orientation block in the
#                     explorer prompt).
#   tools           — model-visible allowlist for the sub-agent.
#   model           — alias ("haiku", "sonnet", "opus", "inherit") or a
#                     full model ID. AgentDefinition has no `thinking`
#                     field — per-subagent reasoning depth is controlled
#                     via `effort` below.
#   effort          — optional "low"|"medium"|"high"|"max" reasoning
#                     budget for the sub-agent. None defers to the SDK
#                     default. Maps onto the model's extended-thinking
#                     budget when the model supports it (Haiku 4.5+,
#                     Sonnet 4+, Opus 4+).
SUBAGENT_REGISTRY: dict[str, dict] = {
    "openfoam2412_repository_explore": {
        "display_name": "OpenFOAM Source Repository Exploration sub-agent",
        "description": (
            "Fast, cheap low-intelligence agent specialized for exploring the "
            "OpenFOAM 2412 installation tree. Call it for very exensive searches "
            "where you are very unsure where the information you need resides."
            "The agent can then indentify relevant files and snippets such that you can read them yourself"
            "When calling this agent, provide thorough context "
            "to it, such that it can fully reason about what "
            "files will be needed to fulfill your needs and "
            "update its search accordingly when specific "
            "information is found in the files (e.g. give it full context of the current case). \n"
            "IMPORTANT: this is a low-intelligence model, do not delegate understanding to it or rely on it to figure out open-ended research questions. Use it purely to help explore and identify relevant files quikly, but not use it to synthesize, perform research and answer open-ended questions."
        ),
        "prompt_template": "openFoam2412_repository_explore.txt",
        "tools": ["Bash", "Read", "Glob", "Grep"],
        "model": "haiku",
        "effort": None,
    },
    "cfd_general_purpose": {
        "display_name": "CFD General Purpose sub-agent",
        "description": (
            "General purpose agent for self-contained complex "
            "multi-step tasks. E.g. researching complex questions, "
            "setting up visualizations, extensive search and synthesis "
            "over the openFoam2412 source repository, reflecting over "
            "iteration history to surface non-obvious solutions etc. "
            "This agent is specialized with tools for this project, "
            "always prefer this agent over the generic "
            "'general-purpose' sub-agent. Use only if you are "
            "confident it will be of large benefit."
        ),
        "prompt_template": "cfd_general_purpose_draft.txt",
        # No "Agent" — the SDK blocks sub-sub-agent delegation, so
        # exposing the verb here would be inert. Everything else
        # mirrors the improver's own tool surface (minus the
        # approval/phase-advance tools, which belong to the parent
        # only).
        "tools": [
            "Read", "Write", "Edit", "Glob", "Grep", "Bash",
            "WebSearch", "web_fetch", "Monitor", "web_fetch",
            *PARAVIEW_READ_TOOLS,
            *PARAVIEW_WRITE_TOOLS,
            PARAVIEW_EXEC_TOOL,
        ],
        "model": "claude-opus-4-6",
        # `thinking` is not exposed on AgentDefinition, so adaptive
        # thinking is not configurable for sub-agents — `effort` is
        # the only reasoning-depth knob the SDK supports here.
        "effort": "high",
    },
    "verification": {
        "display_name": "Verification sub-agent",
        "description": (
            "Use this agent to verify a completed sub-step. The agent "
            "has no prior knowledge about the case, project, nor your sub-task "
            "and will need to be informed. The agent will return a "
            "PASS/FAIL verdict and issues ranked by severity "
            "(blocker / should-fix / nice-to-have), each with concrete evidence."
        ),
        "prompt_template": "verfication_sub_agent.txt",
        "tools": [
            "Read", "Write", "Edit", "Glob", "Grep", "Bash",
            "WebSearch", "web_fetch", "Monitor", "web_fetch",
            *PARAVIEW_READ_TOOLS,
            *PARAVIEW_WRITE_TOOLS,
            PARAVIEW_EXEC_TOOL,
        ],
        "model": "claude-sonnet-4-6",
        "effort": "high",
    },
    "paraview_operator": {
        "display_name": "ParaView Operator sub-agent",
        "description": (
            "ParaView mutation specialist for multi-step scene setup. Delegate to this sub-agent "
            "for complex multistep paraview visualization tasks (that requires changing the user's live "
            "ParaView scene — applying or deleting filters, changing "
            "display/representation/colouring, moving the camera, "
            "toggling patches, advancing time, etc.) Example intents: "
            "\"set up a good view of the mesh\", \"visualise the "
            "problem cells\", \n"
            "The operator handles the full task: planning the sequence "
            "of filter/display/camera changes, executing them via the "
            "ParaView bridge, iterating with screenshots when the "
            "intent is visual, and reporting back a structured summary "
            "of the new ParaView state. It does NOT take read-only "
            "questions that your own ParaView verbs (`get_pipeline`, "
            "`get_source_info`, `save_screenshot`, …) can answer — "
            "call those yourself first when you just need orientation.\n"
            "Give the operator thorough context: the understanding you "
            "already have of the user's ParaView state, relevant "
            "constraints from earlier in the conversation, and the "
            "user's literal request. The more context you pass, the "
            "less time the operator spends re-reading state."
        ),
        "prompt_template": "paraview_operator.txt",
        # Computed from the PARAVIEW_* constants so the registry can't
        # drift from the actual MCP tool surface — adding a new bridge
        # verb to either module flows through here without an edit.
        "tools": PARAVIEW_READ_TOOLS + PARAVIEW_WRITE_TOOLS + [PARAVIEW_EXEC_TOOL],
        "model": "claude-sonnet-4-5",
        "effort": "medium",
    },
}


# ── Phase registry ──
# Per-phase keys:
#   model            — model ID passed to ClaudeAgentOptions.model
#   prompt_template  — file in prompts/, formatted with {expertise_level}
#   tools            — string IDs of tools the model SEES in its schema.
#                      Built-in Claude Code tools (WebSearch, Read, …) are
#                      listed verbatim; custom SDK MCP tools resolve to
#                      `mcp__<server>__<tool>` inside src.tools. Anything
#                      omitted from this list does not exist from the
#                      model's perspective. Forwarded to
#                      ClaudeAgentOptions.tools.
#   allowed_tools    — Subset of `tools` that auto-approves without going
#                      through the `can_use_tool` callback. Tools that are
#                      in `tools` but not here remain callable but each
#                      invocation is gated by the user. Forwarded to
#                      ClaudeAgentOptions.allowed_tools.
#   permission_mode  — Forwarded to ClaudeAgentOptions.permission_mode.
#                      Always "default" so non-allowlisted tools route to
#                      the `can_use_tool` callback. Phases whose visible
#                      tool set is fully covered by `allowed_tools` simply
#                      never trigger the callback — no special-casing needed.
#   effort           — "low" | "medium" | "high" | "max" | None.
#                      None defers to SDK default.
#   thinking         — extended-thinking config dict, one of:
#                          {"type": "enabled",  "budget_tokens": N} - do not use, streaming will disable then
#                          {"type": "adaptive"}
#                          {"type": "disabled"}
#                      or None to defer to SDK default.
#   hooks            — dict mapping hook event name (e.g. "PreToolUse",
#                      "PostToolUse", "Stop", …) to a list of HookMatcher
#                      objects, or None for no hooks. See HookMatcher in
#                      claude_agent_sdk for matcher/callback/timeout shape.
#   max_turns        — bound on agent loop iterations within a single
#                      user turn. Forwarded to ClaudeAgentOptions.max_turns.
#   subagents        — optional list of sub-agent NAMES (strings) that
#                      key into SUBAGENT_REGISTRY above. The phase loads
#                      each one and hands the resulting AgentDefinition
#                      dict to ClaudeAgentOptions.agents. Defining a
#                      sub-agent once in the registry and referencing it
#                      by name keeps phases declarative — multiple phases
#                      can share the same sub-agent without duplication.
#                      Per-tool gating is NOT a separate sub-agent
#                      setting: the SDK has no per-subagent allowed_tools
#                      field, so auto-approval is governed by the
#                      parent's `allowed_tools` plus the shared
#                      `can_use_tool` callback (which receives `agent_id`
#                      so it can branch per sub-agent if needed). For us
#                      today this means anything in the sub-agent's
#                      `tools` that's ALSO in the parent's `allowed_tools`
#                      is auto-approved; everything else routes through
#                      the callback (e.g. Bash).
PHASE_CONFIGS: dict[str, dict] = {
    "simulation_spec": {
        "model": "claude-opus-4-8",
        "prompt_template": "simulation_specification_final_w_Write_Edit.txt",
        # web_fetch (custom) replaces the built-in WebFetch. It is in `tools` but
        # NOT in `allowed_tools`, so each call gates through can_use_tool — same
        # posture the built-in WebFetch had. project_dir is threaded into
        # build_tooling (see run_simulation_spec_turn) to bind its per-project cache.
        "tools": ["present_specification", "WebSearch", "web_fetch", "paper_search", "AskUserQuestion", "Bash", "Read", "Write", "Edit", *PARAVIEW_READ_TOOLS,
           ],
        "allowed_tools": ["present_specification", "Write", "Edit", *PARAVIEW_READ_TOOLS, "Bash"],
        "permission_mode": "default",
        "effort": "high",
        "thinking": {"type": "adaptive", "display": "summarized"},
        "hooks": None,
        "max_turns": 100,
    },
    "case_builder": {
        "model": "claude-sonnet-4-6",
        "prompt_template": "case_builder_with_explore_agent.txt",
        "tools": [
            "Read", "Write", "Edit", "Glob", "Grep", "Bash",
            "Agent", "web_fetch", "paper_search", "Monitor",
            "request_phase_advance",
        ],
        # Bash is intentionally excluded — it routes through the
        # permission callback so the user vets each shell command.
        # Agent is auto-approved: the gating happens on the tools the
        # subagent itself calls, which re-enter `can_use_tool`.
        "allowed_tools": [
            "Read", "Write", "Edit", "Glob", "Grep",
            "Agent", "Bash", "web_fetch", "paper_search", "Monitor",
            "request_phase_advance",
        ],
        "permission_mode": "default",
        "effort": "high",
        "thinking": {"type": "adaptive", "display": "summarized"},
        "hooks": None,
        "max_turns": 60,
        "subagents": ["openfoam2412_repository_explore"],
    },
    "mesh": {
        "model": "claude-opus-4-8[1m]",
        "prompt_template": "mesh_agent_w_verification.txt",
        "tools": [
            "Read", "Write", "Edit", "Glob", "Grep", "Bash", "Monitor",
            "Agent", "WebSearch","web_fetch", "paper_search",
            *PARAVIEW_READ_TOOLS,
            *PARAVIEW_WRITE_TOOLS,
            PARAVIEW_EXEC_TOOL,
            PARAVIEW_LAUNCH_TOOL,
            "request_subtask_approval",
            "request_phase_advance",
        ],
        # Bash and paraview_exec are intentionally excluded so they
        # route through the permission callback. The operator
        # sub-agent's write surface is NOT pre-approved here — those
        # requests float up to the user naturally in production (the
        # phase-4 test bug was a test-harness gap, not a production
        # constraint).
        "allowed_tools": [
            "Read", "Write", "Edit", "Glob", "Grep", "Monitor",
            "Agent", "WebSearch", "Bash",
            "paper_search", "web_fetch",
            *PARAVIEW_READ_TOOLS,
            *PARAVIEW_WRITE_TOOLS,
            PARAVIEW_EXEC_TOOL,
            "request_subtask_approval",
            "request_phase_advance",
        ],
        "permission_mode": "default",
        "effort": "xhigh",
        "thinking": {"type": "adaptive", "display": "summarized"},
        "hooks": None,
        "max_turns": 2000,
        "subagents": [
            "openfoam2412_repository_explore",
            "cfd_general_purpose",
            "verification"
        ],
    },
    "improver": {
        "model": "claude-opus-4-8[1m]",
        "prompt_template": "improver_updated_updated.txt",
        "tools": [
            "Read", "Write", "Edit", "Glob", "Grep", "Bash",
            "Agent", "WebSearch", "web_fetch", "paper_search", "Monitor", "web_fetch",
            *PARAVIEW_READ_TOOLS,
            *PARAVIEW_WRITE_TOOLS,
            PARAVIEW_EXEC_TOOL,
            PARAVIEW_LAUNCH_TOOL,
            "request_experiment_approval",
            "request_mesh_approval",
            "request_phase_advance",
        ],
        # Bash and paraview_exec route through the permission callback
        # so the user vets shell + arbitrary-Python invocations.
        # ParaView write verbs likewise gated. Agent is auto-approved:
        # the gating happens on tools the sub-agent itself calls,
        # which re-enter `can_use_tool`.
        "allowed_tools": [
            "Read", "Write", "Edit", "Glob", "Grep", "Bash",
            "Agent", "WebSearch", "paper_search", "Monitor", "web_fetch",
            *PARAVIEW_READ_TOOLS,
            *PARAVIEW_WRITE_TOOLS,
            PARAVIEW_EXEC_TOOL,
            PARAVIEW_LAUNCH_TOOL,
            "request_experiment_approval",
            "request_mesh_approval",
            "request_phase_advance",
        ],
        "permission_mode": "default",
        "effort": "high",
        "thinking": {"type": "adaptive", "display": "summarized"},
        "hooks": None,
        "max_turns": 20000,
        # Only cfd_general_purpose is exposed — paraview_operator and
        # openfoam2412_repository_explore are intentionally NOT in the
        # improver's agents dict. Sub-agents cannot re-delegate (SDK
        # enforces) so cfd_general_purpose has no `Agent` tool in its
        # own surface and can't reach those specialists either.
        "subagents": ["cfd_general_purpose"],
    },
    "post_process": {
        "model": "claude-sonnet-4-6",
        "prompt_template": "post_process.txt",
        "tools": [
            "Read", "Write", "Edit", "Glob", "Grep", "Bash",
            "Agent", "WebSearch", "web_fetch", "paper_search", "AskUserQuestion", "Skill",
            *PARAVIEW_READ_TOOLS,
            PARAVIEW_EXEC_TOOL,
            PARAVIEW_LAUNCH_TOOL,
        ],
        # Bash and paraview_exec are intentionally excluded so they
        # route through the permission callback — the user vets shell +
        # arbitrary-Python invocations (pyvista figures, pandoc/latex
        # builds, the html-report inliner). AskUserQuestion is handled
        # by the dedicated path in core.py, not via allowed_tools.
        "allowed_tools": [
            "Read", "Write", "Edit", "Glob", "Grep",
            "Agent", "WebSearch", "paper_search", "Skill",
            *PARAVIEW_READ_TOOLS, "Bash",
        ],
        "permission_mode": "default",
        "effort": "high",
        "thinking": {"type": "adaptive"},
        "hooks": None,
        "max_turns": 200,
        # Top-level `skills` filter for this phase: only these are
        # visible (names match each SKILL.md `name:` field, not the
        # directory). The post_process handler forwards this list as
        # `skills=` into run_turn, which is what injects the `Skill`
        # tool and scopes which skills the model can see.
        "skills": ["latex-report", "html-report", "visualization"],
        # cfd_general_purpose handles heavy visualization/research
        # delegation (it already carries bash + paraview + websearch).
        "subagents": ["cfd_general_purpose"],
    },
}
