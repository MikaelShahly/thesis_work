"""Shared agent-loop primitives on top of claude-agent-sdk.

The per-turn driver now lives in `src.agent.session_manager.SessionWorker`
(a persistent client per (project, phase) session). This module keeps the
pieces the worker reuses: the `StreamEvent` vocabulary, the approval-tool
predicates, the `_SegmentAccumulator`, and the raw-stream / tool-result
translators that map SDK message types into the events the frontend
understands.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


# ── Events ─────────────────────────────────────────────────────────────
@dataclass
class StreamEvent:
    type: str
    data: dict[str, Any] = field(default_factory=dict)


# Event type catalogue (forwarded to frontend unless noted):
#
# Subagent scope: streaming events that originate from inside a
# sub-agent invocation carry `parent_tool_use_id` (the id of the parent
# `Agent` tool call) so the UI can prefix or nest them. Top-level
# (parent-agent) events have `parent_tool_use_id: null`. Permission
# requests additionally carry `agent_id` (the SDK's sub-agent id from
# `ToolPermissionContext.agent_id`) — also null for parent-scope calls.
#
#   thinking_started        — agent started reasoning,
#                             {"parent_tool_use_id": str|null}
#   thinking_delta          — streamed reasoning chunk,
#                             {"content": str,
#                              "parent_tool_use_id": str|null}.
#                             Appended to the matching running thinking
#                             segment by scope. Optional — only emitted
#                             when the model streams thinking; absent
#                             when thinking is disabled.
#   thinking_text           — assembled reasoning content,
#                             {"content": str,
#                              "parent_tool_use_id": str|null}.
#                             Authoritative final snapshot — overwrites
#                             whatever the deltas summed to (idempotent
#                             when streaming was complete). Pairs with
#                             the matching thinking_started by
#                             content_block index.
#   text_delta              — response token, {"content": str,
#                             "parent_tool_use_id": str|null}
#   tool_started            — tool call began, {"tool": str, "id": str,
#                             "parent_tool_use_id": str|null}
#   tool_input              — assembled tool input, {"id": str,
#                             "tool": str, "input": dict,
#                             "parent_tool_use_id": str|null}
#   tool_output             — tool result returned, {"tool_use_id": str,
#                             "content": str, "is_error": bool,
#                             "parent_tool_use_id": str|null}
#   status                  — informational, {"message": str}
#   specification_presented — present_specification invoked, {"markdown": str}
#   subtask_approval_requested
#                           — request_subtask_approval (mesh phase) OR
#                             request_mesh_approval (improver phase)
#                             invoked, {}. Both tools share this event
#                             — same approval_kind="mesh_step", same
#                             feedback prefix, same approve endpoint.
#                             API persists approval_pending with
#                             approval_kind="mesh_step".
#   experiment_approval_requested
#                           — request_experiment_approval invoked
#                             (improver phase), {} (API persists
#                             approval_pending with
#                             approval_kind="improver_experiment")
#   phase_advance_requested — request_phase_advance invoked (case_builder,
#                             mesh, or improver phase), {}. API persists
#                             approval_pending with approval_kind set
#                             phase-aware: "case_builder_phase_advance",
#                             "mesh_phase_advance", or
#                             "improver_phase_advance". On approval the
#                             route advances directly (handoff + spec are
#                             already on disk); there is no commit step.
#   file_written            — Write/Edit landed inside the project dir,
#                             {"path": str, "subfolder": str}
#   compaction_started      — CLI began auto/manual context compaction
#                             (PreCompact hook), {"trigger": str}. No
#                             regular messages stream until it finishes;
#                             the UI shows a "compacting…" indicator.
#   compaction_complete     — compaction finished (compact_boundary),
#                             {"trigger": str, "pre_tokens": int|null,
#                              "post_tokens": int|null}. The API layer
#                             persists a `compaction` message row so the
#                             divider survives reload.
#   permission_requested    — agent wants to call a non-allowlisted tool;
#                             UI must POST a decision back via the
#                             permission HTTP route. Payload:
#                             {"tool_use_id": str, "tool": str,
#                              "input": dict, "agent_id": str|null}
#   question_requested      — agent called AskUserQuestion; UI shows the
#                             QuestionPanel and POSTs the answers back via
#                             the question HTTP route, which resolves the
#                             paused Future with an Allow carrying the
#                             selections. Payload: {"tool_use_id": str,
#                             "questions": list, "agent_id": str|null}.
#                             agent_id is always null (sub-agents can't
#                             call this tool).
#   turn_complete           — turn finished, {"stop_reason": str}
#   error                   — failure, {"message": str, "recoverable": bool}
#
# Internal (consumed by API layer, never forwarded):
#   sdk_session_id          — capture session_id for persistence,
#                             {"session_id": str}
#   turn_persist            — incremental persistence checkpoint, emitted
#                             once per completed event (tool output,
#                             thinking, sub-agent text) and at turn end,
#                             {"text": str, "segments": list[dict]} (the
#                             current full snapshot). The API layer upserts
#                             it so a crash mid-turn keeps completed events.
#   model_call              — one API response finished, {"model": str,
#                             "usage": dict, "message_id": str|null,
#                             "stop_reason": str|null,
#                             "parent_tool_use_id": str|null,
#                             "error": str|null}. Persisted to model_calls.
#   session_config          — system prompt + build config, emitted once
#                             per session at init. Persisted to
#                             session_config.
#   agent_event             — reliability/error record, {"kind": str,
#                             "data": dict}. Persisted to agent_events.
#   subagent_narration      — a sub-agent's intermediate text, read from
#                             its transcript at SubagentStop (not on the
#                             live stream), {"agent_id": str|null,
#                             "agent_type": str|null, "texts": list[str]}.
#                             Persisted to subagent_narration; record-only,
#                             not shown in the UI.
#   assistant_turn          — end-of-turn snapshot for DB persistence,
#                             {"text": str, "segments": list[dict]}.
#                             `text` is the parent-agent prose (same
#                             string the old `assistant_text` event
#                             carried, kept for the legacy `content`
#                             column). `segments` is the ordered
#                             breakdown that reproduces the live chat
#                             on reload — text/thinking/tool entries
#                             with `parent_tool_use_id` preserved so
#                             the frontend can reconstruct sub-agent
#                             labels.


_PRESENT_SPEC_TOOL = "present_specification"
_REQUEST_SUBTASK_APPROVAL_TOOL = "request_subtask_approval"
_REQUEST_MESH_APPROVAL_TOOL = "request_mesh_approval"
_REQUEST_EXPERIMENT_APPROVAL_TOOL = "request_experiment_approval"
_REQUEST_PHASE_ADVANCE_TOOL = "request_phase_advance"
_ASK_USER_QUESTION_TOOL = "AskUserQuestion"

# Maximum time the agent waits for the user to click Allow/Deny before we
# return a deny on its behalf. Long enough to leave a prompt visible
# while the user reads, short enough that an abandoned tab doesn't park
# the SDK subprocess forever.
_PERMISSION_TIMEOUT_S = 600

# AskUserQuestion is a deliberate checkpoint where the user is expected to
# think, so it gets a much longer leash than a mid-flow permission prompt.
# On timeout we don't deny — we let the tool run with an empty answer and
# a `response` telling the model to proceed with sensible defaults, so an
# idle user doesn't strand the turn.
_QUESTION_TIMEOUT_S = 3600
_QUESTION_TIMEOUT_RESPONSE = (
    "No response from the user within the time limit. "
    "Proceed using reasonable defaults of your own choosing."
)


def _is_present_spec(name: str) -> bool:
    # MCP tool names arrive as `mcp__<server>__<tool>`; the bare suffix
    # is what we care about.
    return name == _PRESENT_SPEC_TOOL or name.endswith(f"__{_PRESENT_SPEC_TOOL}")


def _is_subtask_approval(name: str) -> bool:
    return (
        name == _REQUEST_SUBTASK_APPROVAL_TOOL
        or name.endswith(f"__{_REQUEST_SUBTASK_APPROVAL_TOOL}")
    )


def _is_mesh_approval(name: str) -> bool:
    # Improver-phase mesh approval. Reuses the same SSE event as
    # `request_subtask_approval` — see the dispatch block below.
    return (
        name == _REQUEST_MESH_APPROVAL_TOOL
        or name.endswith(f"__{_REQUEST_MESH_APPROVAL_TOOL}")
    )


def _is_experiment_approval(name: str) -> bool:
    return (
        name == _REQUEST_EXPERIMENT_APPROVAL_TOOL
        or name.endswith(f"__{_REQUEST_EXPERIMENT_APPROVAL_TOOL}")
    )


def _is_phase_advance(name: str) -> bool:
    return (
        name == _REQUEST_PHASE_ADVANCE_TOOL
        or name.endswith(f"__{_REQUEST_PHASE_ADVANCE_TOOL}")
    )


def _is_ask_user_question(name: str) -> bool:
    # Built-in SDK tool; arrives as the bare name, but match the MCP-style
    # suffix too for safety.
    return (
        name == _ASK_USER_QUESTION_TOOL
        or name.endswith(f"__{_ASK_USER_QUESTION_TOOL}")
    )


def _short_tool_name(name: str) -> str:
    return name.split("__")[-1]


# Sentinel placed on the queue when the SDK consumer is done so the
# outer generator knows to stop draining.
_END: Any = object()


# Persisted tool outputs are capped — bash dumps / file reads can reach
# megabytes and we don't want to bloat SQLite. The live stream is
# untouched; only the row written at end-of-turn is truncated.
_TOOL_OUTPUT_CAP_CHARS = 64_000
_TOOL_OUTPUT_TRUNCATION_MARKER = "\n…[truncated]"


def _cap_tool_output(s: str) -> str:
    if len(s) <= _TOOL_OUTPUT_CAP_CHARS:
        return s
    return s[:_TOOL_OUTPUT_CAP_CHARS] + _TOOL_OUTPUT_TRUNCATION_MARKER


class _SegmentAccumulator:
    """Builds the ordered segment list that the frontend re-hydrates on
    reload. Mirrors the reducer in `useAgentStream.js` for the three
    grouping behaviours that matter:

    * text deltas of the same scope coalesce into a single text segment;
    * `thinking_started` opens a running thinking segment that
      `thinking_text` fills in;
    * `tool_started` opens a tool segment that later `tool_input` and
      `tool_output` events update by `tool_use_id`.

    Sub-agent attribution is preserved via `parent_tool_use_id` on
    every segment — the frontend walks the list in order on reload and
    derives the `agentLabel` from the `Agent` tool's `subagent_type`
    input, just like the live path.
    """

    def __init__(self) -> None:
        self.segments: list[dict[str, Any]] = []
        self._tools_by_id: dict[str, dict[str, Any]] = {}
        # The most recent running thinking segment per scope. The SDK
        # delivers a thinking block as `thinking_started` (synthesized
        # from `content_block_start`) immediately followed at end of
        # the AssistantMessage by `thinking_text` — same scope, same
        # block — so a single pointer per `parent_tool_use_id` is
        # sufficient.
        self._open_thinking: dict[Any, dict[str, Any]] = {}

    def add_text_delta(self, content: str, ptu: str | None) -> None:
        if not content:
            return
        tail = self.segments[-1] if self.segments else None
        if (
            tail is not None
            and tail["kind"] == "text"
            and tail.get("parent_tool_use_id") == ptu
        ):
            tail["content"] = (tail["content"] or "") + content
            return
        self.segments.append({
            "kind": "text",
            "content": content,
            "parent_tool_use_id": ptu,
        })

    def add_thinking_started(self, ptu: str | None) -> None:
        seg = {
            "kind": "thinking",
            "content": "",
            "parent_tool_use_id": ptu,
        }
        self.segments.append(seg)
        self._open_thinking[ptu] = seg

    def add_thinking_delta(self, content: str, ptu: str | None) -> None:
        if not content:
            return
        seg = self._open_thinking.get(ptu)
        if seg is None:
            # Defensive: delta arrived without a matching
            # thinking_started. Open one so the chunk isn't lost.
            self.add_thinking_started(ptu)
            seg = self._open_thinking[ptu]
        seg["content"] = (seg["content"] or "") + content

    def add_thinking_text(self, content: str, ptu: str | None) -> None:
        seg = self._open_thinking.pop(ptu, None)
        if seg is not None:
            seg["content"] = content
            return
        # Defensive: thinking_text arrived without a matching
        # thinking_started. Push a standalone segment so the content
        # isn't lost.
        self.segments.append({
            "kind": "thinking",
            "content": content,
            "parent_tool_use_id": ptu,
        })

    def _ensure_tool(self, tool_use_id: str, ptu: str | None) -> dict[str, Any]:
        seg = self._tools_by_id.get(tool_use_id)
        if seg is not None:
            return seg
        seg = {
            "kind": "tool",
            "tool_use_id": tool_use_id,
            "tool_name": None,
            "tool_input": None,
            "content": None,
            "tool_is_error": False,
            "parent_tool_use_id": ptu,
        }
        self._tools_by_id[tool_use_id] = seg
        self.segments.append(seg)
        return seg

    def add_tool_started(
        self, tool_use_id: str, tool: str, ptu: str | None
    ) -> None:
        if not tool_use_id:
            return
        seg = self._ensure_tool(tool_use_id, ptu)
        if not seg.get("tool_name"):
            seg["tool_name"] = tool

    def add_tool_input(
        self,
        tool_use_id: str,
        tool: str,
        tool_input: dict[str, Any],
        ptu: str | None,
    ) -> None:
        if not tool_use_id:
            return
        seg = self._ensure_tool(tool_use_id, ptu)
        seg["tool_name"] = tool
        try:
            seg["tool_input"] = json.dumps(tool_input)
        except (TypeError, ValueError):
            # Fall back to a repr if the input has non-JSON-serializable
            # values — the live stream uses `block.input` directly so
            # this only affects persistence.
            seg["tool_input"] = json.dumps({"_repr": repr(tool_input)})

    def add_tool_output(
        self,
        tool_use_id: str,
        content: str,
        is_error: bool,
        ptu: str | None,
    ) -> None:
        if not tool_use_id:
            return
        seg = self._ensure_tool(tool_use_id, ptu)
        seg["content"] = _cap_tool_output(content or "")
        seg["tool_is_error"] = bool(is_error)


def _translate_stream_event(raw: dict) -> list[StreamEvent]:
    """Map a raw Anthropic stream event dict to our StreamEvent vocabulary."""
    etype = raw.get("type")
    out: list[StreamEvent] = []

    if etype == "content_block_start":
        block = raw.get("content_block", {})
        btype = block.get("type")
        if btype == "thinking":
            # No id surfaced — thinking blocks have no client-side id.
            # The frontend pairs this with the next `thinking_text` by
            # matching the most-recent running segment.
            out.append(StreamEvent("thinking_started", {}))
        elif btype in ("tool_use", "server_tool_use"):
            name = block.get("name", "")
            tool_id = block.get("id", "") or ""
            out.append(StreamEvent("tool_started", {
                "tool": _short_tool_name(name),
                "id": tool_id,
            }))

    elif etype == "content_block_delta":
        delta = raw.get("delta", {})
        if delta.get("type") == "text_delta":
            text = delta.get("text", "")
            if text:
                out.append(StreamEvent("text_delta", {"content": text}))
        elif delta.get("type") == "thinking_delta":
            text = delta.get("thinking", "")
            if text:
                out.append(StreamEvent("thinking_delta", {"content": text}))

    return out


def _normalize_tool_result_content(content: Any) -> str:
    """Coerce a ToolResultBlock.content into a single display string.

    The SDK passes through the wire shape:
      - bare string for simple tools (Write/Edit return a status string)
      - list[dict] for richer results (Bash returns
        [{"type": "text", "text": "<stdout>"}], image-returning tools
        emit {"type": "image", ...})

    We concat the text parts and emit `[image]` placeholders so the UI
    has something to display in the output box.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            itype = item.get("type")
            if itype == "text":
                parts.append(item.get("text", ""))
            elif itype == "image":
                parts.append("[image]")
        return "".join(parts)
    return ""
