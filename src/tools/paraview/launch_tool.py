"""The `launch_paraview` lifecycle tool.

Unlike every other verb in this package — which talks HTTP to an
*already-running* bridge via `bridge_call` — this one spawns the
ParaView process itself. It is the in-agent twin of the frontend's
"open ParaView" toolbar button (POST /paraview/launch): same
`paraview_lifecycle.launch`, same single-instance rule.

Single-tenancy, the agent's way: we ping the bridge first and refuse to
launch if anything already answers. Unlike the HTTP route's
orphan-recovery path, we never SIGKILL a live instance to take the slot
— an instance the agent didn't start might be the user's, and killing it
is the user's gesture, not ours.

Project context comes from `active_project_id()`: the per-worker
PreToolUse guard (`make_paraview_guard`) already ensures only the active
project's session can reach any `mcp__paraview__*` tool, so the active
project is this caller's project. We resolve its directory the same way
the HTTP route does (`PROJECTS_DIR / folder_name`).
"""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool


def _err(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "is_error": True}


def _ok(payload: dict) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}]}


@tool(
    "launch_paraview",
    (
        "Open ParaView (with the bridge attached) for the active "
        "project — the same thing the toolbar button does, but from the "
        "agent. Use this when no ParaView is running and you need it for "
        "visualisation.\n\n"
        "**Ping first.** Before launching, confirm nothing is already "
        "up: call `ping`. If it succeeds, ParaView is already open — "
        "do NOT launch (this tool will refuse anyway). Only one instance "
        "can exist at a time, and this tool will never close or replace "
        "a running one.\n\n"
        "On success returns the launch record `{pid, project_name, "
        "port, ...}`. After it returns, the bridge is reachable: `ping` "
        "to learn `project_root`, then `load_dataset` your case."
    ),
    {"type": "object", "properties": {}},
)
async def launch_paraview(args: dict[str, Any]) -> dict[str, Any]:
    # Lazy imports: this module is pulled in by the paraview package
    # `__init__`, which `src.config` imports at module load — importing
    # config (PROJECTS_DIR) at top level would close that cycle.
    from src import db
    from src.agent.paraview_owner import active_project_id
    from src.config import PROJECTS_DIR
    from src.paraview import lifecycle as paraview_lifecycle

    # Refuse if any instance (ours or an orphan) is already answering.
    if paraview_lifecycle.is_bridge_up():
        return _err(
            "ParaView is already open. Use the existing instance — "
            "`ping` it and carry on. This tool will not launch a second "
            "instance or close the running one."
        )

    project_id = active_project_id()
    if project_id is None:
        return _err(
            "No active project, so there is nowhere to anchor ParaView. "
            "This should not happen in normal use — surface it rather "
            "than retrying."
        )

    project = db.get_project(project_id)
    if project is None:
        return _err(f"Active project {project_id!r} not found in the database.")

    proj_dir = PROJECTS_DIR / project["folder_name"]

    try:
        record = await paraview_lifecycle.launch(
            project_dir=proj_dir,
            project_id=project["id"],
            project_name=project["name"],
        )
    except paraview_lifecycle.ParaviewAlreadyRunningError as e:
        # Raced with another launcher between our ping and the spawn.
        return _err(str(e))
    except paraview_lifecycle.ParaviewLaunchError as e:
        return _err(f"ParaView failed to launch: {e}")

    return _ok({"status": "launched", **record})
