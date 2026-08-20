"""The request_mesh_approval tool (improver phase).

Called by the improver agent after an experiment changes the mesh,
before launching the solver on the new mesh. Surfaces the new mesh
to the user so a bad mesh is caught before solver compute is spent
on it.

Reuses the mesh phase's `subtask_approval_requested` SSE event
wiring — i.e. the same `approval_kind="mesh_step"`, the same
`[Feedback on mesh]:` feedback prefix, and the same
`/approve-mesh-step` endpoint (generalised in the route layer to
also handle the improver phase). Sub-step approval semantics:
approving does NOT advance the phase, it injects a "Proceed"
message so the agent resumes for the next step in the experiment.

The string returned below is only what the agent itself sees.
"""

from typing import Any

from claude_agent_sdk import tool


@tool(
    "request_mesh_approval",
    (
        "Request the user's approval for the current mesh before "
        "launching the solver. Call this after an approved "
        "experiment changes the mesh — once the new mesh is built, "
        "verified, and visible in "
        "ParaView (case has an up-to-date `.foam` file; bridge "
        "pinged so the user can reload).\n\n"
        "Do NOT use this for experiment-plan approval "
        "(`request_experiment_approval`) or for the terminal phase "
        "advance (`request_phase_advance`).\n\n"
        "Takes no arguments. On approval the system will inject a "
        "'Proceed' message and you will resume to launch the solver. "
        "On feedback (a revision request), address the changes "
        "(re-run only the invalidated mesh stages per the workflow "
        "in your system prompt) and call this tool again. On a "
        "question, answer it; only re-call this tool if the answer "
        "involved actually editing files. The approval pill "
        "persists across question turns."
    ),
    {},
)
async def request_mesh_approval(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    "Mesh approval requested. Awaiting the user's "
                    "response. They will either approve (the system "
                    "will inject a 'Proceed' message and you will "
                    "resume to launch the solver), provide feedback "
                    "prefixed with [Feedback on mesh]: (treat as a "
                    "revision request — re-run only the invalidated "
                    "mesh stages from the appropriate snapshot, "
                    "re-verify, and call request_mesh_approval again), "
                    "or ask a follow-up question (answer it; only "
                    "call request_mesh_approval again if your answer "
                    "involved actually editing files)."
                ),
            }
        ]
    }
