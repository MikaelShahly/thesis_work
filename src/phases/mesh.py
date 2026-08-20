"""Mesh phase handler.

Reads the approved simulation specification (written to disk by
/approve-spec), embeds it into the system prompt along with the
absolute geometry directory path, and delegates to the shared agent
loop.

Two differences from case_builder:
- `cwd` is the project root (not Case/) so the agent can cross
  Specification/, Case/, and Geometry/ with relative paths.
- The prompt embeds `{geometry_dir}` as an absolute path so the
  agent finds user-uploaded geometry deterministically.
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

from src.agent.core import StreamEvent
from src.agent.session_manager import run_via_worker
from src.agent.subagents import build_subagents
from src.config import (
    CFMESH_TUTORIALS_DIR,
    MESH_ADVICE_DIR,
    OPENFOAM_SOURCE_DIR,
    PHASE_CONFIGS,
    PROMPTS_DIR,
)
from src.tools import build_tooling


_phase_cfg = PHASE_CONFIGS["mesh"]
_PROMPT_TEMPLATE = (PROMPTS_DIR / _phase_cfg["prompt_template"]).read_text()
# Sub-agent tool union flows to `build_tooling` as `extra_mcp_tools`
# so any tool a delegated sub-agent might call is registered in the
# MCP servers, even when the parent itself doesn't expose it.
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


def build_system_prompt(
    spec_markdown: str, geometry_dir: str, project_dir: str
) -> str:
    return _PROMPT_TEMPLATE.format(
        simulation_specification=spec_markdown,
        openfoam_source_dir=OPENFOAM_SOURCE_DIR,
        mesh_advice_dir=MESH_ADVICE_DIR,
        cfmesh_tutorials_dir=CFMESH_TUTORIALS_DIR,
        geometry_dir=geometry_dir,
        project_dir=project_dir,
    )


async def run_mesh_turn(
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
        project_dir=project_dir,
    )

    geometry_dir = project_dir / "Geometry"
    # No mkdir — Geometry/ is materialised at project creation.

    async for event in run_via_worker(
        session_key=f"{project_id}:mesh",
        user_message=user_message,
        system_prompt=build_system_prompt(
            _read_spec(project_dir),
            str(geometry_dir),
            str(project_dir),
        ),
        model=_phase_cfg["model"],
        tools=tools,
        allowed_tools=allowed_tools,
        mcp_servers=mcp_servers,
        resume_session_id=resume_session_id,
        max_turns=_phase_cfg["max_turns"],
        # cwd is the project root, NOT Case/. The mesh agent reads the
        # spec from Specification/, geometry from Geometry/, and writes
        # mesh dictionaries to Case/system/, so relative paths must
        # resolve against the root.
        project_dir=project_dir,
        project_id=project_id,
        cwd=project_dir,
        permission_mode=_phase_cfg.get("permission_mode", "default"),
        effort=_phase_cfg.get("effort"),
        thinking=_phase_cfg.get("thinking"),
        hooks=_phase_cfg.get("hooks"),
        agents=_SUBAGENTS,
    ):
        yield event
