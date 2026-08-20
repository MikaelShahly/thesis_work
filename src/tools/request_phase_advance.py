"""The request_phase_advance tool.

Phase-agnostic: called by any agent at the end of its phase to
request the user's final sign-off and hand off to the next phase.
The handoff document and updated spec are written BEFORE this call,
so on approval the backend advances directly — there is no separate
commit step or post-approval handoff turn.
Current callers:
- Case builder (case_builder → mesh)
- Mesh agent (mesh → improver)
- Improver agent (improver → post-process)

The agent layer detects the ToolUseBlock as it streams by and emits
a `phase_advance_requested` SSE event. The API layer flips
`projects.approval_pending` and sets `approval_kind` to a phase-
specific discriminator (e.g. `case_builder_phase_advance`,
`mesh_phase_advance`, `improver_phase_advance`) — the discriminator
is chosen from the project's current phase, not from the tool itself,
so the UI shows the right copy and restores state on reload.

The string returned below is what the agent sees.
"""

from typing import Any

from claude_agent_sdk import tool


@tool(
    "request_phase_advance",
    (
        "Request the user's approval to advance to the next agent phase. "
        "This is the terminal gesture of your phase — call it once your "
        "task is complete and all artifacts are organised.\n\n"
        "BEFORE calling: write your handoff document "
        "(handoffs/<phase>.md) and bring the simulation specification up to "
        "date so they reflect the CURRENT state of the case. The user "
        "approves with these on disk; on approval the pipeline advances "
        "directly to the next phase (no further turn for you).\n\n"
        "Do NOT use this for intermediate sub-step approvals.\n\n"
        "Takes no arguments. The user will either approve (the pipeline "
        "advances; you will not see that turn), reply with feedback "
        "prefixed by [Feedback]:, or ask a follow-up question. The "
        "approval pill stays up across question turns until the user "
        "approves or sends feedback."
    ),
    {},
)
async def request_phase_advance(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    "Phase-advance approval requested. Your turn ends "
                    "here — do not call further tools or write more "
                    "files. The user will either approve (the pipeline "
                    "advances directly to the next phase; you will not "
                    "see that turn), provide feedback prefixed with "
                    "[Feedback]: (treat as a revision request — make the "
                    "changes, update the handoff and spec to match, "
                    "re-verify, and call request_phase_advance again), "
                    "or ask a follow-up question (answer it; only call "
                    "request_phase_advance again if your answer involved "
                    "actually editing files)."
                ),
            }
        ]
    }
