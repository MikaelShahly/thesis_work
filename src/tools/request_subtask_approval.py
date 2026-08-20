"""The request_subtask_approval tool (mesh phase).

Called by the mesh agent after each verifiable meshing sub-step
(blockMesh, snappy castellation, snap, layers, …) to surface the
result for the user's review. Unlike `request_phase_advance`, approving
this does NOT advance the phase — the backend pushes a synthetic
"continue" message and the agent's loop resumes for the next
sub-task.

The agent layer detects the ToolUseBlock as it streams by and emits
a `subtask_approval_requested` SSE event; the API layer also flips
`projects.approval_pending` and sets `approval_kind="mesh_step"` so
the state survives a page reload.

The string returned below is only what the agent itself sees.
"""

from typing import Any

from claude_agent_sdk import tool


@tool(
    "request_subtask_approval",
    (
        "Request the user's approval for the current mesh sub-step. "
        "Call this for the initial mesh plan and then for each mesh "
        "sub-step (blockMesh, snappyHexMesh castellation, snap, layer "
        "addition, …) after it has been thoroughly verified.\n\n"
        "Do NOT call this at the end of the whole meshing phase — use "
        "`request_phase_advance` for that.\n\n"
        "Takes no arguments. The user will either approve (the system "
        "will inject a 'Proceed' message and you will resume for the "
        "next sub-task), reply with feedback prefixed by "
        "[Feedback on mesh]:, or ask a follow-up question. It is "
        "normal — and expected — to call this multiple times across "
        "a meshing session."
    ),
    {},
)
async def request_subtask_approval(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    "Approval requested for the current mesh sub-step. "
                    "Awaiting the user's response. They will either approve "
                    "(the system will inject a 'Proceed' message and you "
                    "will resume), provide feedback prefixed with "
                    "[Feedback on mesh]: (treat as a revision request — "
                    "edit the relevant dictionaries, re-run only the "
                    "invalidated meshing stages, re-verify, and call "
                    "request_subtask_approval again), or ask a follow-up "
                    "question (answer it; only call request_subtask_approval "
                    "again if your answer involved actually editing files). — otherwise the existing approval still"
                    "stands and the user can approve from the pill when ready."
                ),
            }
        ]
    }
