"""The present_specification tool.

Called by the simulation-spec agent when it has a complete draft ready
for the user to review. The agent layer also inspects the tool-use
input as it streams by and forwards the markdown to the API as a
`specification_presented` event — that side panel rendering happens
there. The return value below is only what the agent itself sees.
"""

from typing import Any

from claude_agent_sdk import tool


@tool(
    "present_specification",
    (
        "Present the completed simulation specification to the user for review. "
        "The specification will be displayed in a side panel where the user "
        "can either approve it or provide feedback for revisions.\n\n"
        "Before calling this tool, write (or edit) the specification markdown "
        "to {project_dir}/Specification/simulation_specification.md, then pass "
        "the absolute path to that file as `specification_path`.\n\n"
        "The specification markdown file must contain two sections:\n"
        "1. CASE SPECIFICATION — all information needed to set up the "
        "OpenFOAM case. This includes, but is not limited to (solver, boundary conditions, turbulence model, "
        "fluid properties, domain, time control, numerical schemes, etc.)\n"
        "2. CASE GOAL — the user's desired outcome, quantities of interest, "
        "success criteria, and convergence targets.\n\n"
        "All assumed or inferred parameters must be tagged inline with "
        "[ASSUMED] or [INFERRED], and a consolidated Assumptions & Reasoning "
        "section must appear at the end with justifications and any citations."
    ),
    {"specification_path": str},
)
async def present_specification(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    "Specification presented to user for review. "
                    "Awaiting their response. They will either approve the "
                    "specification, provide feedback for revisions, or ask "
                    "a follow-up question. If they ask a question, answer it "
                    "and then call present_specification again when ready."
                ),
            }
        ]
    }
