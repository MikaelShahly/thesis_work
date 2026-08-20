"""Simulation specification phase handler.

Reads config from the phase registry, composes the system prompt with
the user's expertise level, builds tooling, and delegates to the
shared agent loop.
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

from src.agent.core import StreamEvent
from src.agent.session_manager import run_via_worker
from src.config import PHASE_CONFIGS, PROMPTS_DIR
from src.tools import build_tooling


_phase_cfg = PHASE_CONFIGS["simulation_spec"]
_PROMPT_TEMPLATE = (PROMPTS_DIR / _phase_cfg["prompt_template"]).read_text()


def build_system_prompt(expertise_level: str, project_dir: str) -> str:
    return _PROMPT_TEMPLATE.format(
        expertise_level=expertise_level,
        project_dir=project_dir,
    )


async def run_simulation_spec_turn(
    user_message: str,
    expertise_level: str,
    resume_session_id: str | None,
    project_dir: Path,
    project_id: str | None = None,
) -> AsyncIterator[StreamEvent]:
    tools, allowed_tools, mcp_servers = build_tooling(
        _phase_cfg["tools"], _phase_cfg["allowed_tools"], project_dir=project_dir
    )

    async for event in run_via_worker(
        session_key=f"{project_id}:simulation_spec",
        user_message=user_message,
        system_prompt=build_system_prompt(expertise_level, str(project_dir)),
        model=_phase_cfg["model"],
        tools=tools,
        allowed_tools=allowed_tools,
        mcp_servers=mcp_servers,
        resume_session_id=resume_session_id,
        max_turns=_phase_cfg["max_turns"],
        project_dir=project_dir,
        project_id=project_id,
        permission_mode=_phase_cfg.get("permission_mode", "default"),
        effort=_phase_cfg.get("effort"),
        thinking=_phase_cfg.get("thinking"),
        hooks=_phase_cfg.get("hooks"),
    ):
        yield event
