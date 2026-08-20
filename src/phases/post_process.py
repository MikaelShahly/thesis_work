"""Post-processing phase handler.

The last of five phases. Reads the finished, analyzed case from disk and
turns it into the user's deliverables — figures and, when wanted, a
report (HTML / LaTeX-PDF / Markdown). Unlike the improver, this handler
does NOT embed the spec into the system prompt: the post-process prompt
tells the agent to read the spec, case, iterations, and the improver's
handoff itself, so we only substitute the absolute project root.

Mirrors `improver.py`: the `cfd_general_purpose` sub-agent is built
per-turn with `project_dir` baked in (the parent may `cd` away in a Bash
call before delegating, so the sub-agent prompt can't rely on runtime
cwd to resolve relative paths). One addition over the other phases —
`skills` is forwarded into `run_turn`, which is what injects the `Skill`
tool and scopes which `.claude/skills/` the model can see.
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

from src.agent.core import StreamEvent
from src.agent.session_manager import run_via_worker
from src.agent.subagents import build_subagents
from src.config import PHASE_CONFIGS, PROMPTS_DIR
from src.tools import build_tooling


_phase_cfg = PHASE_CONFIGS["post_process"]
_PROMPT_TEMPLATE = (PROMPTS_DIR / _phase_cfg["prompt_template"]).read_text()


def build_system_prompt(project_dir: str) -> str:
    return _PROMPT_TEMPLATE.format(project_dir=project_dir)


async def run_post_process_turn(
    user_message: str,
    expertise_level: str,  # accepted for handler-signature parity; unused
    resume_session_id: str | None,
    project_dir: Path,
    project_id: str | None = None,
) -> AsyncIterator[StreamEvent]:
    subagents, subagent_tool_union = build_subagents(
        _phase_cfg.get("subagents"),
        project_dir=str(project_dir),
    )

    tools, allowed_tools, mcp_servers = build_tooling(
        _phase_cfg["tools"],
        _phase_cfg["allowed_tools"],
        extra_mcp_tools=subagent_tool_union,
        project_dir=project_dir,
    )

    async for event in run_via_worker(
        session_key=f"{project_id}:post_process",
        user_message=user_message,
        system_prompt=build_system_prompt(str(project_dir)),
        model=_phase_cfg["model"],
        tools=tools,
        allowed_tools=allowed_tools,
        mcp_servers=mcp_servers,
        resume_session_id=resume_session_id,
        max_turns=_phase_cfg["max_turns"],
        # cwd is the project root. The agent reads Specification/, Case/,
        # iterations/, handoffs/ and writes deliverables into directories
        # it creates itself.
        project_dir=project_dir,
        project_id=project_id,
        cwd=project_dir,
        permission_mode=_phase_cfg.get("permission_mode", "default"),
        effort=_phase_cfg.get("effort"),
        thinking=_phase_cfg.get("thinking"),
        hooks=_phase_cfg.get("hooks"),
        agents=subagents,
        skills=_phase_cfg.get("skills"),
    ):
        yield event
