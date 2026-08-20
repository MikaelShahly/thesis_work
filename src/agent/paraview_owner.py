"""ParaView single-tenancy: the live bridge belongs to the active project.

The ParaView bridge is a singleton (one HTTP server, one scene, one
`PV_PROJECT_ROOT`) shared with the frontend — so it can only serve one
project at a time. We enforce "only the active project may drive the live
ParaView instance" with:

  * `active_project_id` — a single backend-global (this is a single FastAPI
    process, same pattern as `permissions` / the worker registry). The
    frontend flips it on project switch via POST /projects/{id}/activate.
  * a `PreToolUse` ownership hook — denies ParaView tool calls from any
    session whose project isn't the active one. A `PreToolUse` hook is
    used (not `can_use_tool`) because it fires regardless of `allowed_tools`
    — verified in tests/production/test_hook_overrides_allowlist.py — so a
    project that allowlists ParaView is still gated.

The agent is root-aware (the bridge reports `project_root`, so the active
project pings and loads its own data); we therefore only gate *access*,
never the data — no bridge-owner check, no takeover, no relaunch.
"""

from __future__ import annotations

# ParaView MCP tools are visible to the model as `mcp__paraview__<verb>`
# (see src/tools/paraview/__init__.py).
_PARAVIEW_TOOL_PREFIX = "mcp__paraview__"

_DENY_REASON = (
    "The live ParaView instance is owned by the active project, and the user "
    "has switched to a different project. You can no longer reach the live "
    "ParaView instance — stop trying to connect to it and do not retry. "
    "Continue your work without it; other (offline/static) visualization "
    "methods remain available if you need them."
)

# Single source of truth for "who owns the live ParaView bridge right now".
_active_project_id: str | None = None


def set_active_project(project_id: str | None) -> None:
    """Set the active project (frontend calls this on switch/open)."""
    global _active_project_id
    _active_project_id = project_id


def active_project_id() -> str | None:
    return _active_project_id


def is_paraview_tool(tool_name: str) -> bool:
    return tool_name.startswith(_PARAVIEW_TOOL_PREFIX)


def make_paraview_guard(worker_project_id: str | None):
    """Build a PreToolUse hook bound to a worker's project.

    Denies ParaView tools unless this worker's project is the active one.
    Fail-open when no active project is set (startup / headless / tests) or
    when the worker has no project_id, so the common single-project flow and
    isolation tests are unaffected.
    """

    async def guard(input_data, tool_use_id, context):
        tool_name = input_data.get("tool_name", "")
        if not is_paraview_tool(tool_name):
            return {}
        active = _active_project_id
        if active is None or worker_project_id is None:
            return {}  # nothing to enforce against
        if worker_project_id != active:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": _DENY_REASON,
                }
            }
        return {}  # active project → fall through to normal handling

    return guard
