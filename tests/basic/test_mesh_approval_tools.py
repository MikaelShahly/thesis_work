"""Shape checks for the two new mesh-approval tools.

Confirms that `request_subtask_approval` and `request_phase_advance`:

- Are registered in `_CUSTOM_TOOLS` under the `cfd` server.
- Translate to MCP-prefixed names via `translate_tool_names`.
- Have non-trivial descriptions and return text.
- Are detected by the event-emission helpers in `src/agent/core.py`
  (`_is_subtask_approval`, `_is_phase_advance`) under both bare and
  MCP-prefixed names.
"""

import asyncio

from src.agent.core import (
    _is_phase_advance,
    _is_subtask_approval,
)
from src.tools import CFD_MCP_SERVER_NAME, _CUSTOM_TOOLS, translate_tool_names


def test_merged_tools_are_gone_from_registry_and_configs():
    # request_approval and commit_phase_advance were merged into the
    # single request_phase_advance gate — they must not be registered
    # or referenced by any phase config (a stale entry would make the
    # SDK advertise a tool that no longer exists).
    from src.config import PHASE_CONFIGS

    assert "request_approval" not in _CUSTOM_TOOLS
    assert "commit_phase_advance" not in _CUSTOM_TOOLS

    for phase, cfg in PHASE_CONFIGS.items():
        for key in ("tools", "allowed_tools"):
            surface = cfg.get(key, [])
            assert "request_approval" not in surface, (phase, key)
            assert "commit_phase_advance" not in surface, (phase, key)


def test_both_tools_registered_under_cfd_server():
    assert "request_subtask_approval" in _CUSTOM_TOOLS
    assert "request_phase_advance" in _CUSTOM_TOOLS

    server_a, _ = _CUSTOM_TOOLS["request_subtask_approval"]
    server_b, _ = _CUSTOM_TOOLS["request_phase_advance"]
    assert server_a == CFD_MCP_SERVER_NAME
    assert server_b == CFD_MCP_SERVER_NAME


def test_tools_translate_to_mcp_prefixed_names():
    translated = translate_tool_names([
        "request_subtask_approval",
        "request_phase_advance",
    ])
    assert translated == [
        "mcp__cfd__request_subtask_approval",
        "mcp__cfd__request_phase_advance",
    ]


def test_event_detection_recognises_both_forms():
    # Bare names — caught when running the tool inside the host SDK.
    assert _is_subtask_approval("request_subtask_approval")
    assert _is_phase_advance("request_phase_advance")

    # MCP-prefixed names — what the SDK actually surfaces in
    # ToolUseBlock.name when the tool lives in an MCP server.
    assert _is_subtask_approval("mcp__cfd__request_subtask_approval")
    assert _is_phase_advance("mcp__cfd__request_phase_advance")


def test_detectors_do_not_cross_match():
    # Each detector matches only its own tool — a regression here
    # would emit the wrong SSE event (e.g. firing subtask_approval
    # when the agent called request_phase_advance).
    assert not _is_phase_advance("request_subtask_approval")
    assert not _is_subtask_approval("request_phase_advance")


def _invoke(tool_obj) -> dict:
    """Drive the `@tool`-decorated callable through its declared shape.

    The SDK wraps the underlying coroutine in a `SdkMcpTool` dataclass
    that exposes the handler under `.handler` and the metadata under
    `.name` / `.description` / `.input_schema`. We don't go through
    the MCP server — just confirm the handler returns the expected
    SDK content shape when called directly.
    """
    handler = tool_obj.handler
    return asyncio.run(handler({}))


def test_request_subtask_approval_return_shape():
    _, tool_obj = _CUSTOM_TOOLS["request_subtask_approval"]
    out = _invoke(tool_obj)
    assert "content" in out
    blocks = out["content"]
    assert isinstance(blocks, list) and blocks
    text = blocks[0]["text"]
    # The agent reads this verbatim; confirm the key cues are in
    # place so prompt-level guidance stays consistent.
    assert "sub-step" in text.lower()
    assert "[Feedback on mesh]" in text


def test_request_phase_advance_return_shape():
    _, tool_obj = _CUSTOM_TOOLS["request_phase_advance"]
    out = _invoke(tool_obj)
    assert "content" in out
    text = out["content"][0]["text"]
    # On approval the pipeline advances directly — no commit/handoff turn.
    assert "advances directly" in text.lower()
    # request_phase_advance is phase-agnostic now — its feedback
    # prefix is the generic `[Feedback]:` rather than mesh-specific.
    assert "[Feedback]" in text


def test_descriptions_distinguish_the_two_use_cases():
    _, sub_tool = _CUSTOM_TOOLS["request_subtask_approval"]
    _, adv_tool = _CUSTOM_TOOLS["request_phase_advance"]

    sub_desc = sub_tool.description.lower()
    adv_desc = adv_tool.description.lower()

    # Sub-step description must tell the model NOT to use it for the
    # whole-phase gesture (and vice versa) so the two tools don't get
    # confused at call time.
    assert "request_phase_advance" in sub_desc or "phase" in sub_desc
    assert "sub-step" in adv_desc or "intermediate" in adv_desc
