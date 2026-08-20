"""End-to-end roundtrip for the ``paraview_operator`` sub-agent.

A minimal parent agent (only the ``Agent`` tool, plus read-only
``get_pipeline`` for verification) delegates a single visual task to
the operator against a live ParaView running the sample OpenFOAM
case. After the parent's turn completes, the test introspects
ParaView to verify the operator actually mutated the scene — slice
in the pipeline, some source coloured by ``U``.

The test asserts the **side effects on ParaView**, not the operator's
reply text. The reply is non-deterministic across runs; the pipeline
state is.

Skipped when any of the following are missing:

- ``paraview`` (or ``PARAVIEW_EXECUTABLE``) on PATH — no live bridge.
- ``claude`` CLI on PATH — the Claude Agent SDK shells out to it.
- The sample case (``tests/openFoam_test_case``).
- ``RUN_LIVE_SUBAGENT_TESTS`` env var set — opt-in to avoid burning
  LLM budget on every CI run.

On failure the test dumps the full SDK transcript (every assistant
turn, tool call, tool result) and the last 5 KB of ParaView's
stderr — both are otherwise discarded by the fixture/lifecycle.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from src.agent.subagents import build_subagents
from src.paraview import lifecycle
from src.tools import build_tooling
from src.tools.paraview.read_paraview_state import get_pipeline, get_source_info


_REPO_ROOT = Path(__file__).resolve().parents[2]
# Defacto default sample case for production tests — see
# tests/openFoam_test_case/README.md.
_SAMPLE_CASE = (
    _REPO_ROOT / "tests" / "openFoam_test_case" / "difficult_w_fields.foam"
)


def _paraview_available() -> bool:
    exe = os.environ.get("PARAVIEW_EXECUTABLE")
    if exe and Path(exe).exists():
        return True
    return shutil.which("paraview") is not None


def _claude_cli_available() -> bool:
    return shutil.which("claude") is not None


pytestmark = [
    pytest.mark.paraview,
    pytest.mark.skipif(
        not os.environ.get("RUN_LIVE_SUBAGENT_TESTS"),
        reason=(
            "Live sub-agent roundtrip is opt-in (real LLM calls cost "
            "tokens). Set RUN_LIVE_SUBAGENT_TESTS=1 to enable."
        ),
    ),
    pytest.mark.skipif(
        not _paraview_available(),
        reason="ParaView not on PATH and PARAVIEW_EXECUTABLE not set.",
    ),
    pytest.mark.skipif(
        not _claude_cli_available(),
        reason="Claude Code CLI ('claude') not on PATH.",
    ),
    pytest.mark.skipif(
        not _SAMPLE_CASE.is_file(),
        reason=f"sample case missing at {_SAMPLE_CASE}",
    ),
]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def live_bridge_with_case(tmp_path_factory):
    """Live ParaView with the sample case auto-loaded.

    Mirrors the layout used by the bridge roundtrip fixture so the
    bridge's relative-path anchor (``PV_PROJECT_ROOT``) lines up with
    the fake project root. Module-scoped: one launch, one teardown
    via ``os.killpg``.

    Also patches ``subprocess.Popen`` only while spawning ParaView so
    its stderr lands in a log file we can dump on test failure —
    otherwise it goes to ``DEVNULL`` per ``lifecycle.launch`` and
    we'd have no view of a ParaView crash.
    """
    lifecycle._reset_for_tests()  # noqa: SLF001 — test-only access
    project_dir = tmp_path_factory.mktemp("paraview-operator-project")
    case_root = project_dir / "Cases" / "baseline"
    shutil.copytree(_SAMPLE_CASE.parent, case_root)

    stderr_log_path = project_dir / "paraview.stderr.log"
    stderr_fh = open(stderr_log_path, "ab")
    real_popen = subprocess.Popen

    def _capturing_popen(*args, **kwargs):
        # Replace lifecycle's DEVNULL stderr with our log file so a
        # ParaView crash leaves a trace.
        kwargs["stderr"] = stderr_fh
        return real_popen(*args, **kwargs)

    subprocess.Popen = _capturing_popen  # type: ignore[assignment]

    try:
        await lifecycle.launch(
            project_dir=project_dir,
            project_id="op-test",
            project_name="paraview-operator-roundtrip",
            foam_file=str(case_root / _SAMPLE_CASE.name),
        )
        yield {"project_dir": project_dir, "stderr_log": stderr_log_path}
    finally:
        subprocess.Popen = real_popen  # type: ignore[assignment]
        rec = lifecycle._record  # noqa: SLF001 — test-only access
        if rec is not None and rec.is_alive():
            rec.force_kill(timeout=10.0)
        lifecycle._reset_for_tests()  # noqa: SLF001
        stderr_fh.close()


def _decode_tool_result(result: dict):
    """Pull the JSON payload out of an SDK-shaped tool result."""
    assert not result.get("is_error"), result["content"][0]["text"]
    return json.loads(result["content"][0]["text"])


def _stringify_block(block) -> str:
    """Compact, single-line-ish summary of an SDK content block.

    Goal: legibility of a long transcript on test failure. We trim
    big payloads (tool inputs/outputs) to a reasonable cap so the
    dump doesn't drown the actually useful first/last lines.
    """
    if isinstance(block, TextBlock):
        text = (block.text or "").strip()
        return f"  text: {text[:500]}{'…' if len(text) > 500 else ''}"
    if isinstance(block, ThinkingBlock):
        text = (block.thinking or "").strip()
        return f"  thinking: {text[:300]}{'…' if len(text) > 300 else ''}"
    if isinstance(block, ToolUseBlock):
        inp = json.dumps(block.input, default=str)
        return f"  tool_use: {block.name}({inp[:600]}{'…' if len(inp) > 600 else ''}) id={block.id[:8]}"
    if isinstance(block, ToolResultBlock):
        # ToolResultBlock.content is a string OR a list of dicts.
        if isinstance(block.content, str):
            payload = block.content
        else:
            parts = []
            for item in block.content or []:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
            payload = "".join(parts)
        marker = "ERR" if block.is_error else "ok"
        return f"  tool_result[{marker}] id={block.tool_use_id[:8]}: {payload[:600]}{'…' if len(payload) > 600 else ''}"
    return f"  ?{type(block).__name__}: {block!r}"[:600]


def _stringify_message(msg) -> str:
    """Single-line header for one SDK message."""
    cls = type(msg).__name__
    ptu = getattr(msg, "parent_tool_use_id", None)
    scope = f"sub({ptu[:8]})" if ptu else "parent"
    return f"[{scope}] {cls}"


@pytest.mark.asyncio
async def test_operator_applies_slice_and_colours_by_array(live_bridge_with_case):
    """Real LLM → real operator → real ParaView side-effects.

    The parent's only allowed mutation path is the ``Agent`` tool —
    no ParaView write verbs are visible to it — so any change in the
    pipeline can only come from the operator. The test sends a
    literal "apply a slice through the domain centre normal to X,
    colour by U" request and verifies both halves of the change.
    """
    project_dir = live_bridge_with_case["project_dir"]
    stderr_log_path: Path = live_bridge_with_case["stderr_log"]

    # The operator AgentDefinition is built the same way phases do it.
    agents, subagent_tool_union = build_subagents(["paraview_operator"])
    assert agents is not None and "paraview_operator" in agents

    # Parent surface: just enough to delegate and read back. We
    # intentionally exclude every ParaView WRITE verb from the
    # parent's schema so the test cannot accidentally pass via the
    # parent doing the work itself.
    #
    # `extra_mcp_tools` registers the operator's full surface in the
    # MCP servers (the parent never sees those tools, but the
    # sub-agent can call them). It also flows into `allowed_tools`
    # so SDK-level permission gating doesn't block the sub-agent's
    # calls — without this, every call from inside the operator
    # would route through can_use_tool and loop forever waiting on
    # a callback this minimal test doesn't provide. This mirrors the
    # plan §6 policy: auto-approve reads + writes for the operator
    # (paraview_exec is the only call worth gating, and we accept
    # auto-approving it here for the test's sake).
    parent_tools = ["Agent", "get_pipeline"]
    allowed = parent_tools + subagent_tool_union
    tools, allowed_tools, mcp_servers = build_tooling(
        parent_tools,
        allowed,
        extra_mcp_tools=subagent_tool_union,
    )

    options = ClaudeAgentOptions(
        system_prompt=(
            "You are a test harness driving a sub-agent integration "
            "test. Delegate the user's literal request to the "
            "`paraview_operator` sub-agent via the `Agent` tool, then "
            "respond with a one-line acknowledgement. Do not attempt "
            "to call ParaView verbs yourself."
        ),
        model="claude-sonnet-4-5",
        tools=tools,
        allowed_tools=allowed_tools,
        mcp_servers=mcp_servers,
        permission_mode="default",
        # Bounded so the operator can't burn budget retrying around
        # an unfamiliar quirk. If 15 turns isn't enough we want to
        # see the "ran out of turns" signal in the transcript, not
        # let the agent loop indefinitely.
        agents=agents,
        max_turns=15,
        env={"ENABLE_TOOL_SEARCH": "false"},
        setting_sources=[],
        cwd=str(project_dir),
    )

    # Print each transcript line as it arrives so a stuck or
    # slow-looping run is visible immediately, not after-the-fact.
    # Also accumulate for the failure dump.
    import sys as _sys
    transcript: list[str] = []
    final_result: ResultMessage | None = None

    def _log(line: str) -> None:
        transcript.append(line)
        print(line, flush=True)
        _sys.stdout.flush()

    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(
                "Apply a slice through the domain centre normal to X, and "
                "colour the slice by U."
            )
            async for msg in client.receive_response():
                _log(_stringify_message(msg))
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        _log(_stringify_block(block))
                elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
                    for block in msg.content:
                        _log(_stringify_block(block))
                elif isinstance(msg, SystemMessage):
                    _log(f"  system.subtype={msg.subtype}")
                if isinstance(msg, ResultMessage):
                    final_result = msg
                    _log(
                        f"  stop_reason={msg.stop_reason or msg.subtype} "
                        f"is_error={msg.is_error} "
                        f"num_turns={getattr(msg, 'num_turns', '?')}"
                    )
                    break

        # ── Verify ────────────────────────────────────────────────
        pipeline = _decode_tool_result(await get_pipeline.handler({}))
        assert isinstance(pipeline, list) and pipeline, "pipeline is empty"

        # ParaView calls its slice filter `Slice1` in the user-facing
        # name but the underlying VTK class is `vtkCutter`, surfaced
        # in `type` as `"Cut"`. Match against name + type together so
        # either naming convention satisfies the assertion.
        entries_str = [
            f"name={e.get('name', '')!r} type={e.get('type', '')!r}"
            for e in pipeline
        ]
        looks_like_slice = any(
            "slice" in f"{e.get('name', '')} {e.get('type', '')}".lower()
            or "cut" in f"{e.get('type', '')}".lower()
            for e in pipeline
        )
        assert looks_like_slice, (
            f"no slice / cut filter in pipeline after operator turn; "
            f"entries were {entries_str}"
        )

        # At least one source should be coloured by `U`. The bridge's
        # display block uses `color_by: {mode: "array", array: "U"}`
        # post-`color_by_array`, but the exact key path has shifted
        # across bridge revisions — serialise the display block and
        # look for `"U"` as a quoted value. The display block is
        # small and U is unlikely to appear except as the colour
        # array reference.
        coloured_by_u = False
        for entry in pipeline:
            info = _decode_tool_result(await get_source_info.handler(
                {"input_id": entry.get("id", "")}
            ))
            display = info.get("display") or {}
            if '"U"' in json.dumps(display):
                coloured_by_u = True
                break

        assert coloured_by_u, (
            "no source in the pipeline is coloured by `U` after the "
            f"operator turn — pipeline entries: {entries_str}"
        )
    except Exception:
        # Dump everything that would otherwise be invisible so the
        # next investigator doesn't fly blind.
        print("\n========== SDK TRANSCRIPT ==========")
        for line in transcript:
            print(line)
        if final_result is not None:
            print(
                f"========== FINAL RESULT: {final_result.subtype} "
                f"stop={final_result.stop_reason} "
                f"is_error={final_result.is_error} =========="
            )
        if stderr_log_path.is_file() and stderr_log_path.stat().st_size > 0:
            print(f"\n========== PARAVIEW STDERR (last 5KB) ==========")
            tail = stderr_log_path.read_bytes()[-5000:].decode(
                "utf-8", errors="replace"
            )
            print(tail)
        raise
