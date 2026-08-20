"""The request_experiment_approval tool (improver phase).

Called by the improver agent before running each planned
experiment. Surfaces the diagnosis + plan to the user for sign-off
so a bad plan is caught before any compute is spent on the
experiment. On approve, the backend pushes a synthetic "Proceed"
message and the agent's loop resumes; the phase does NOT advance.

The agent layer detects the ToolUseBlock as it streams by and emits
an `experiment_approval_requested` SSE event; the API layer also
flips `projects.approval_pending` and sets
`approval_kind="improver_experiment"` so the state survives a page
reload.

The string returned below is only what the agent itself sees.
"""

from typing import Any

from claude_agent_sdk import tool


@tool(
    "request_experiment_approval",
    (
        "Request the user's approval for the planned experiment "
        "before running it. Call this after diagnosing why the "
        "current case fails to meet the goal and writing up the "
        "experiment plan in chat — i.e. before spending any compute "
        "on the experiment.\n\n"
        "Do NOT use this for mesh approval mid-experiment "
        "(`request_mesh_approval`) or for the terminal phase "
        "advance (`request_phase_advance`).\n\n"
        "Takes no arguments. On approval the system will inject a "
        "'Proceed' message and you will resume to run the "
        "experiment. On feedback (a revision request), address the "
        "changes and call this tool again. On a question, answer it; "
        "only re-call this tool if the answer involved actually "
        "editing files. The approval pill persists across question "
        "turns. It is normal — and expected — to call this multiple "
        "times across an improver session, once per experiment."
    ),
    {},
)
async def request_experiment_approval(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    "Experiment-plan approval requested. Awaiting the "
                    "user's response. They will either approve (the "
                    "system will inject a 'Proceed' message and you "
                    "will resume to run the experiment), provide "
                    "feedback prefixed with [Feedback on experiment]: "
                    "(treat as a revision request — adjust the plan, "
                    "re-summarise, and call request_experiment_approval "
                    "again), or ask a follow-up question (answer it; "
                    "only call request_experiment_approval again if "
                    "your answer involved actually editing files)."
                ),
            }
        ]
    }
