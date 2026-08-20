"""Smoke tests for Agent Skills — real SDK round-trip.

Exercises the two things static checks can't prove:

1. discovery   — the CLI finds `.claude/skills/` via
                 `setting_sources=["project"]` and lists all three skills.
2. invocation  — an agent actually fires the built-in `Skill` tool when a
                 prompt matches a skill description.

Run directly (each costs a real subscription turn):

    uv run python tests/production/test_skills_smoke.py discovery
    uv run python tests/production/test_skills_smoke.py invocation

Authenticates via the Claude Code subscription only — strips API-key env
vars first, mirroring src/api/app.py.
"""

from __future__ import annotations

import os

# Mirror src/api/app.py: subscription auth only, never API key. Must run
# before the SDK builds the subprocess env.
for _k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
    os.environ.pop(_k, None)

import asyncio
import sys
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, query

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {"latex-report", "html-report", "visualization"}
TIMEOUT_S = 180


def _text_blocks(msg) -> list[str]:
    out = []
    for block in getattr(msg, "content", None) or []:
        if getattr(block, "text", None):
            out.append(block.text)
    return out


def _tool_uses(msg) -> list[tuple[str, dict]]:
    out = []
    for block in getattr(msg, "content", None) or []:
        # ToolUseBlock has .name and .input
        if getattr(block, "name", None) and hasattr(block, "input"):
            out.append((block.name, getattr(block, "input", {}) or {}))
    return out


async def discovery() -> bool:
    """Ask the model to list discovered skills — proves discovery works."""
    options = ClaudeAgentOptions(
        cwd=str(PROJECT_ROOT),
        setting_sources=["project"],
        skills="all",
        allowed_tools=[],  # answer from the skill listing, no tools needed
        env={"ENABLE_TOOL_SEARCH": "false"},
        max_turns=2,
    )
    prompt = (
        "List the exact `name` of every Agent Skill available to you, "
        "one per line. Do not use any tools — answer from your skill "
        "listing only."
    )
    chunks: list[str] = []
    async for msg in query(prompt=prompt, options=options):
        chunks.extend(_text_blocks(msg))
        if getattr(msg, "result", None):
            chunks.append(msg.result)

    text = "\n".join(chunks)
    print("--- model output ---")
    print(text)
    print("--------------------")
    found = {s for s in EXPECTED if s in text}
    missing = EXPECTED - found
    if missing:
        print(f"FAIL: missing {missing}")
        return False
    print(f"PASS: all three skills discovered {sorted(found)}")
    return True


async def invocation() -> bool:
    """Prompt that matches a skill description; confirm the Skill tool fires.

    Breaks the moment a `Skill` tool_use appears — before it executes, so
    no files are written by the skill's scripts.
    """
    # Filter the session to a single skill BY ITS FRONTMATTER NAME
    # (`latex-report`), even though its folder is `LaTeX-report`. If the
    # Skill tool fires, the frontmatter-name identifier resolved through
    # the filter — settling the dir-vs-name question empirically.
    options = ClaudeAgentOptions(
        cwd=str(PROJECT_ROOT),
        setting_sources=["project"],
        skills=["latex-report"],
        allowed_tools=["Skill", "Read"],
        env={"ENABLE_TOOL_SEARCH": "false"},
        max_turns=3,
    )
    prompt = (
        "Use your latex-report skill to begin producing a LaTeX report. "
        "Invoke the skill now."
    )
    fired: str | None = None
    async for msg in query(prompt=prompt, options=options):
        for name, tin in _tool_uses(msg):
            print(f"tool_use: {name} {tin if name == 'Skill' else ''}")
            if name == "Skill":
                fired = tin.get("command") or tin.get("name") or str(tin)
                break
        if fired is not None:
            break

    if fired is None:
        print("FAIL: model never invoked the Skill tool")
        return False
    print(f"PASS: Skill tool invoked -> {fired}")
    return True


TESTS = {"discovery": discovery, "invocation": invocation}


async def _run(name: str) -> int:
    try:
        ok = await asyncio.wait_for(TESTS[name](), timeout=TIMEOUT_S)
    except asyncio.TimeoutError:
        print(f"FAIL: {name} timed out after {TIMEOUT_S}s")
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "discovery"
    if which not in TESTS:
        print(f"usage: {sys.argv[0]} [{'|'.join(TESTS)}]")
        sys.exit(2)
    sys.exit(asyncio.run(_run(which)))
