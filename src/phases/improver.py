"""Improver phase handler.

Reads the approved simulation specification (written to disk by
/approve-spec, propagated unchanged through the case_builder and
mesh phases), embeds it into the system prompt along with the
absolute project root and OpenFOAM source paths, and delegates to
the shared agent loop.

One difference from `mesh.py`: `build_subagents()` is called *inside*
the turn handler (not at module scope) with `project_dir` substituted
into sub-agent prompts. The improver's sub-agent
(`cfd_general_purpose`) references the project root by absolute
path, and the parent improver may `cd` away in a Bash call before
delegating — so the sub-agent prompt can't rely on the parent's
runtime cwd to resolve relative paths.
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


_phase_cfg = PHASE_CONFIGS["improver"]
_PROMPT_TEMPLATE = (PROMPTS_DIR / _phase_cfg["prompt_template"]).read_text()


def _read_spec(project_dir: Path) -> str:
    spec_path = project_dir / "Specification" / "simulation_specification.md"
    if not spec_path.is_file():
        # The spec is written by /approve-spec; if it's missing this
        # late in the pipeline we have a phase-transition bug.
        raise FileNotFoundError(
            f"Approved specification not found at {spec_path}. "
            "Was /approve-spec run for this project?"
        )
    return spec_path.read_text()


def build_system_prompt(spec_markdown: str, project_dir: str) -> str:
    return _PROMPT_TEMPLATE.format(
        simulation_specification=spec_markdown,
        project_dir=project_dir,
        openfoam_source_dir=OPENFOAM_SOURCE_DIR,
        mesh_advice_dir=MESH_ADVICE_DIR,
        cfmesh_tutorials_dir=CFMESH_TUTORIALS_DIR,
    )


async def run_improver_turn(
    user_message: str,
    expertise_level: str,  # accepted for handler-signature parity; unused
    resume_session_id: str | None,
    project_dir: Path,
    project_id: str | None = None,
) -> AsyncIterator[StreamEvent]:
    # Sub-agents are built per-turn with the absolute project_dir
    # baked in. The tool union flows to `build_tooling` as
    # `extra_mcp_tools` so any tool the sub-agent might call is
    # registered in the MCP servers, even when the parent itself
    # doesn't expose it.
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
        session_key=f"{project_id}:improver",
        user_message=user_message,
        system_prompt=build_system_prompt(
            _read_spec(project_dir),
            str(project_dir),
        ),
        model=_phase_cfg["model"],
        tools=tools,
        allowed_tools=allowed_tools,
        mcp_servers=mcp_servers,
        resume_session_id=resume_session_id,
        max_turns=_phase_cfg["max_turns"],
        # cwd is the project root. The improver reads spec, case,
        # mesh, geometry, and writes iterations/, all under the
        # project root. Sub-agents inherit this cwd but
        # also receive `{project_dir}` substituted into their prompts
        # so they don't rely on cwd that the parent may `cd` away
        # from.
        project_dir=project_dir,
        project_id=project_id,
        cwd=project_dir,
        permission_mode=_phase_cfg.get("permission_mode", "default"),
        effort=_phase_cfg.get("effort"),
        thinking=_phase_cfg.get("thinking"),
        hooks=_phase_cfg.get("hooks"),
        agents=subagents,
    ):
        yield event
