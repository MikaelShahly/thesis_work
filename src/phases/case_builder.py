"""Case builder phase handler.

Reads the approved simulation specification (written to disk by
/approve-spec) and embeds it into the system prompt, then delegates
to the shared agent loop with cwd at the project root. The agent
creates one named case per study under Cases/ (e.g. Cases/baseline/).
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

from src.agent.core import StreamEvent
from src.agent.session_manager import run_via_worker
from src.agent.subagents import build_subagents
from src.config import OPENFOAM_SOURCE_DIR, PHASE_CONFIGS, PROMPTS_DIR
from src.tools import build_tooling


_phase_cfg = PHASE_CONFIGS["case_builder"]
_PROMPT_TEMPLATE = (PROMPTS_DIR / _phase_cfg["prompt_template"]).read_text()
# Sub-agent tool union flows to `build_tooling` as `extra_mcp_tools`
# so any tool a delegated agent might call is registered in the MCP
# servers, even when the parent itself doesn't expose it.
_SUBAGENTS, _SUBAGENT_TOOL_UNION = build_subagents(_phase_cfg.get("subagents"))


def _read_spec(project_dir: Path) -> str:
    spec_path = project_dir / "Specification" / "simulation_specification.md"
    if not spec_path.is_file():
        # The spec is written by /approve-spec; if it's missing we have
        # a phase-transition bug rather than a recoverable runtime
        # condition. Surface it loudly.
        raise FileNotFoundError(
            f"Approved specification not found at {spec_path}. "
            "Was /approve-spec run for this project?"
        )
    return spec_path.read_text()


def build_system_prompt(spec_markdown: str, project_dir: str) -> str:
    return _PROMPT_TEMPLATE.format(
        simulation_specification=spec_markdown,
        openfoam_source_dir=OPENFOAM_SOURCE_DIR,
        project_dir=project_dir,
    )


async def run_case_builder_turn(
    user_message: str,
    expertise_level: str,  # accepted for handler-signature parity; unused
    resume_session_id: str | None,
    project_dir: Path,
    project_id: str | None = None,
) -> AsyncIterator[StreamEvent]:
    tools, allowed_tools, mcp_servers = build_tooling(
        _phase_cfg["tools"],
        _phase_cfg["allowed_tools"],
        extra_mcp_tools=_SUBAGENT_TOOL_UNION,
    )

    async for event in run_via_worker(
        session_key=f"{project_id}:case_builder",
        user_message=user_message,
        system_prompt=build_system_prompt(_read_spec(project_dir), str(project_dir)),
        model=_phase_cfg["model"],
        tools=tools,
        allowed_tools=allowed_tools,
        mcp_servers=mcp_servers,
        resume_session_id=resume_session_id,
        max_turns=_phase_cfg["max_turns"],
        # cwd defaults to the project root so the agent creates and
        # writes into Cases/<name>/ itself, and the file-write hook
        # classifies writes by their first segment (Cases, …).
        project_dir=project_dir,
        project_id=project_id,
        permission_mode=_phase_cfg.get("permission_mode", "default"),
        effort=_phase_cfg.get("effort"),
        thinking=_phase_cfg.get("thinking"),
        hooks=_phase_cfg.get("hooks"),
        agents=_SUBAGENTS,
    ):
        yield event
