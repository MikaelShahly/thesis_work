"""Persistent per-agent session worker.

A `SessionWorker` owns ONE long-lived `ClaudeSDKClient` for the lifetime
of a phase-agent session (keyed by the DB session id). Unlike the old
per-turn `run_turn` — which connected, ran one turn, and tore the
subprocess down — the worker keeps the subprocess alive between turns so
that `run_in_background` jobs survive, and runs a single *continuous*
receive loop so background-task completion (`TaskNotificationMessage`)
is observed even while the agent is idle.

Design (mirrors the conclusions in the implementation plan):

  * One worker per (project, phase) session. Subagents share it.
  * The worker connects the client inside its own task (the SDK pins a
    client to the async context it was connected in) and runs the
    continuous `receive_messages()` loop there.
  * `submit_turn()` is the per-turn entry point: it injects a user
    message and yields the translated `StreamEvent`s for that turn until
    `turn_complete`. A single-consumer lock serialises turns — one turn
    at a time per worker.
  * Turn-scoped messages (text / thinking / tool / result) are demuxed
    to the active turn's queue. Task-lifecycle messages
    (`TaskStartedMessage` / `TaskNotificationMessage`) update
    `running_tasks` at any time, including between turns.

The message-translation logic is reused verbatim from `core.py` so the
event vocabulary the frontend sees is unchanged.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    CLIConnectionError,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    PermissionResult,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    StreamEvent as SdkStreamEvent,
    SystemMessage,
    TaskNotificationMessage,
    TaskStartedMessage,
    TextBlock,
    ThinkingBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from src.agent import permissions
from src.agent.paraview_owner import make_paraview_guard
from src.agent.core import (
    StreamEvent,
    _SegmentAccumulator,
    _is_ask_user_question,
    _is_experiment_approval,
    _is_mesh_approval,
    _is_phase_advance,
    _is_present_spec,
    _is_subtask_approval,
    _normalize_tool_result_content,
    _short_tool_name,
    _translate_stream_event,
    _PERMISSION_TIMEOUT_S,
    _QUESTION_TIMEOUT_S,
    _QUESTION_TIMEOUT_RESPONSE,
)
from src.agent.hooks import build_file_write_tracker, merge_hooks

# Sentinel pushed onto a turn's queue when its ResultMessage is seen, so
# `submit_turn` knows to stop yielding.
_TURN_END: Any = object()


def _extract_subagent_texts(path: str) -> list[str]:
    """Read a sub-agent transcript JSONL and return its assistant text
    blocks in order. Tolerant of partial / malformed lines and a missing
    file (the transcript is CLI-owned and may have rotated)."""
    out: list[str] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("type") != "assistant":
                    continue
                msg = rec.get("message")
                content = msg.get("content") if isinstance(msg, dict) else None
                for block in content or []:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = (block.get("text") or "").strip()
                        if text:
                            out.append(text)
    except OSError:
        return out
    return out


async def run_via_worker(
    *, session_key: str, user_message: str, **worker_kwargs: Any
) -> AsyncIterator[StreamEvent]:
    """Drop-in for run_turn that routes a turn through a persistent worker.

    `session_key` is the per-(project, phase) key; the worker is created
    once and reused across turns. Phase handlers call this with the same
    kwargs they used to pass to run_turn (minus the run_turn-only ones).
    """
    # Lazy import to avoid a module-level cycle (registry imports us).
    from src.agent import session_registry

    def factory(resume_override: str | None = None) -> "SessionWorker":
        kw = dict(worker_kwargs)
        if resume_override is not None:
            kw["resume_session_id"] = resume_override
        return SessionWorker(
            session_id=session_key,
            on_state_change=session_registry.on_worker_state_change,
            on_autonomous_turn=session_registry.on_autonomous_turn,
            **kw,
        )

    worker = await session_registry.get_or_create(session_key, factory)
    try:
        async for event in worker.submit_turn(user_message):
            yield event
    except CLIConnectionError:
        # Subprocess was terminated externally (e.g. SIGTERM). Evict the
        # dead worker, reconnect resuming the same SDK session, and retry.
        resume_id = worker.sdk_session_id
        await session_registry.close_session(session_key)
        worker = await session_registry.get_or_create(
            session_key, lambda: factory(resume_id)
        )
        async for event in worker.submit_turn(user_message):
            yield event


class SessionWorker:
    """A persistent client + continuous receive loop for one session."""

    def __init__(
        self,
        *,
        session_id: str,
        system_prompt: str,
        model: str,
        tools: list[str],
        allowed_tools: list[str],
        mcp_servers: dict,
        resume_session_id: str | None,
        max_turns: int,
        project_dir: Path,
        project_id: str | None = None,
        cwd: Path | None = None,
        permission_mode: str = "default",
        effort: str | None = None,
        thinking: dict | None = None,
        hooks: dict | None = None,
        agents: dict[str, AgentDefinition] | None = None,
        skills: list[str] | None = None,
        on_state_change: Callable[["SessionWorker"], None] | None = None,
        on_autonomous_turn: Callable[["SessionWorker", asyncio.Queue], None]
        | None = None,
    ) -> None:
        self.session_id = session_id
        self.project_id = project_id
        self.project_dir = project_dir
        self._sdk_cwd = cwd or project_dir
        self._on_state_change = on_state_change
        # Fired when the worker starts a turn the user didn't ask for — the
        # SDK re-invoked the agent on its own after a background-task /
        # Monitor wake-up. Lets the route layer attach a buffer + persist
        # task so the wake-up turn is streamed and saved like any other.
        self._on_autonomous_turn = on_autonomous_turn

        # Live SDK session id (from init / result). Carried so the API
        # layer can persist it for resume.
        self.sdk_session_id: str | None = resume_session_id

        # ── State the lifecycle layer reads ──
        self.turn_active: bool = False
        self.running_tasks: set[str] = set()
        # Set before client.interrupt() so the terminal ResultMessage
        # (flagged is_error by the CLI) is classified as a clean user
        # interrupt rather than a real failure.
        self._interrupted: bool = False

        # ── Per-turn state (reset each submit_turn) ──
        self._turn_out: asyncio.Queue[Any] | None = None
        self._segments: _SegmentAccumulator | None = None
        self._assistant_text_parts: list[str] = []

        # One turn at a time per worker. Acquired by submit_turn, released
        # by the worker when the turn actually completes (ResultMessage) —
        # NOT when submit_turn's generator closes — so an SSE disconnect
        # doesn't free the turn / mark the session idle early.
        self._turn_lock = asyncio.Lock()
        self._turn_lock_held = False
        # Serialise permission prompts within a turn.
        self._gate_lock = asyncio.Lock()

        self._client: ClaudeSDKClient | None = None
        self._run_task: asyncio.Task | None = None
        self._file_event_queue: asyncio.Queue | None = None
        self._closed = False

        self._options = self._build_options(
            system_prompt=system_prompt,
            model=model,
            tools=tools,
            allowed_tools=allowed_tools,
            mcp_servers=mcp_servers,
            resume_session_id=resume_session_id,
            max_turns=max_turns,
            permission_mode=permission_mode,
            effort=effort,
            thinking=thinking,
            hooks=hooks,
            agents=agents,
            skills=skills,
        )

        # Observability: the system prompt + config the agent was built
        # with. Captured here because it only exists in-process (never in
        # the SDK transcript). Emitted once per session as `session_config`
        # so the API layer persists it. See docs/observability_design.md.
        self._config_snapshot = {
            "system_prompt": system_prompt,
            "model": model,
            "effort": effort,
            "thinking": thinking,
            "max_turns": max_turns,
            "permission_mode": permission_mode,
            "allowed_tools": allowed_tools,
            "mcp_servers": list(mcp_servers.keys()) if isinstance(mcp_servers, dict) else None,
            "skills": skills,
            "cwd": str(self._sdk_cwd),
        }
        self._config_emitted = False

    # ── lifecycle ──────────────────────────────────────────────────────
    @property
    def client(self) -> ClaudeSDKClient | None:
        return self._client

    def is_idle(self) -> bool:
        """No active turn and no live background task."""
        return not self.turn_active and not self.running_tasks

    async def start(self) -> None:
        """Connect the client and spawn the continuous receive loop."""
        self._client = ClaudeSDKClient(options=self._options)
        await self._client.connect()
        self._run_task = asyncio.create_task(self._run())

    async def close(self) -> None:
        """Tear down the receive loop and disconnect the client.

        Caller is responsible for the policy (never close while a task is
        running, never the active project) — this just performs it.
        """
        self._closed = True
        # Unblock any waiting turn consumer and release the lock.
        if self._turn_out is not None:
            try:
                self._turn_out.put_nowait(_TURN_END)
            except Exception:
                pass
        self._end_turn()
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()
            try:
                await self._run_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass

    async def interrupt(self) -> None:
        # Flag first so a fast terminal ResultMessage is classified as a
        # clean interrupt before the consumer sees it.
        self._interrupted = True
        if self._client is not None:
            await self._client.interrupt()

    # ── per-turn entry point ───────────────────────────────────────────
    async def submit_turn(self, user_message: str) -> AsyncIterator[StreamEvent]:
        """Run one turn: inject `user_message`, yield its StreamEvents.

        Serialised: a second concurrent call blocks on the turn lock (the
        API layer should reject concurrent turns up front with 409).

        Critically, if the *consumer* stops early (SSE disconnect), the
        turn keeps running in the worker — the lock and `turn_active` are
        released by the worker at ResultMessage, not here — so the
        subprocess and any background job survive, and the close-check
        won't reap a still-running session.
        """
        if self._client is None or self._closed:
            raise RuntimeError("SessionWorker not started or already closed")

        await self._turn_lock.acquire()
        self._begin_turn()
        out = self._turn_out

        try:
            await self._client.query(user_message)
        except Exception:
            # Query failed before the turn could run — release ownership
            # so the session isn't deadlocked.
            self._end_turn()
            raise

        async for ev in self.consume_turn(out):
            yield ev

    def _begin_turn(self) -> None:
        """Set up per-turn state and take turn ownership.

        Shared by user-initiated turns (`submit_turn`) and autonomous turns
        the worker starts itself (`_begin_autonomous_turn`)."""
        self._turn_out = asyncio.Queue()
        self._segments = _SegmentAccumulator()
        self._assistant_text_parts = []
        self._interrupted = False
        self._turn_lock_held = True
        self.turn_active = True

    async def consume_turn(
        self, out: asyncio.Queue | None = None
    ) -> AsyncIterator[StreamEvent]:
        """Yield a turn's StreamEvents until it completes (`_TURN_END`).

        The consumer half shared by `submit_turn` (user turns) and the route
        layer's autonomous-turn drive task. `out` is captured by the caller
        at turn start, so a fast turn boundary that nulls `self._turn_out`
        can't strand events already queued on the object."""
        if out is None:
            out = self._turn_out
        if out is None:
            return
        while True:
            ev = await out.get()
            if ev is _TURN_END:
                return
            yield ev

    async def _begin_autonomous_turn(self) -> None:
        """The agent was re-invoked by the SDK with no `submit_turn` driving
        it (a background-task / Monitor wake-up). Take turn ownership and
        hand the fresh turn queue to the route layer so the wake-up turn is
        buffered, streamed, and persisted like any user turn.

        The turn lock is free here: this only fires when `turn_active` is
        False, and the lock is released together with `turn_active` in
        `_end_turn`."""
        await self._turn_lock.acquire()
        self._begin_turn()
        if self._on_autonomous_turn is not None:
            try:
                self._on_autonomous_turn(self, self._turn_out)
            except Exception:
                pass

    def _end_turn(self) -> None:
        """Release turn ownership exactly once (idempotent).

        Called by the worker when the turn truly completes (ResultMessage),
        on a turn error, or on close — never from submit_turn's generator
        teardown.
        """
        self.turn_active = False
        # Null the per-turn queue so "no active consumer" is detectable: the
        # next turn-content event arriving on the receive loop with
        # `_turn_out is None` is an autonomous (wake-up) turn. Leaving it
        # set would silently route wake-up events onto a dead queue.
        self._turn_out = None
        self._segments = None
        if self._turn_lock_held:
            self._turn_lock_held = False
            try:
                self._turn_lock.release()
            except RuntimeError:
                pass
        self._notify_state_change()

    # ── internals ──────────────────────────────────────────────────────
    def _notify_state_change(self) -> None:
        if self._on_state_change is not None:
            try:
                self._on_state_change(self)
            except Exception:
                pass

    async def _emit(self, ev: StreamEvent) -> None:
        """Push an event to the active turn's queue (drop if no turn)."""
        if self._turn_out is not None:
            await self._turn_out.put(ev)

    async def _emit_turn_persist(self) -> None:
        """Checkpoint the turn's current snapshot for incremental DB
        persistence. Fired on each completed event (tool output, thinking,
        sub-agent text) so a crash mid-turn keeps the work already done.
        Internal — the API layer upserts it; not forwarded to the client."""
        if self._segments is None:
            return
        text = "".join(self._assistant_text_parts).strip()
        await self._emit(StreamEvent("turn_persist", {
            "text": text,
            "segments": self._segments.segments,
        }))

    def _drain_file_events(self) -> list[StreamEvent]:
        out: list[StreamEvent] = []
        if self._file_event_queue is None:
            return out
        while True:
            try:
                rec = self._file_event_queue.get_nowait()
            except asyncio.QueueEmpty:
                return out
            out.append(StreamEvent("file_written", rec))

    def _build_options(
        self,
        *,
        system_prompt: str,
        model: str,
        tools: list[str],
        allowed_tools: list[str],
        mcp_servers: dict,
        resume_session_id: str | None,
        max_turns: int,
        permission_mode: str,
        effort: str | None,
        thinking: dict | None,
        hooks: dict | None,
        agents: dict[str, AgentDefinition] | None,
        skills: list[str] | None,
    ) -> ClaudeAgentOptions:
        # File-write tracker (built once for the worker's lifetime).
        self._file_event_queue, write_hooks = build_file_write_tracker(
            self.project_dir, self._sdk_cwd
        )
        precompact_hooks = {"PreCompact": [HookMatcher(hooks=[self._on_pre_compact])]}
        # ParaView single-tenancy: deny ParaView tools when this worker's
        # project isn't the active one. PreToolUse fires regardless of
        # allowed_tools, so it holds even if a phase allowlists ParaView.
        paraview_hooks = {
            "PreToolUse": [HookMatcher(hooks=[make_paraview_guard(self.project_id)])],
        }
        # Sub-agent narration isn't on the live stream — only in the
        # sub-agent's transcript. SubagentStop hands us that file path when
        # the sub-agent finishes; we read it and persist the text (§ db
        # subagent_narration). Record-only, not shown in the UI.
        subagent_hooks = {
            "SubagentStop": [HookMatcher(hooks=[self._on_subagent_stop])],
        }
        combined_hooks = merge_hooks(
            hooks, write_hooks, precompact_hooks, paraview_hooks, subagent_hooks,
        )

        return ClaudeAgentOptions(
            system_prompt=system_prompt,
            model=model,
            tools=tools,
            allowed_tools=allowed_tools,
            mcp_servers=mcp_servers,
            permission_mode=permission_mode,
            can_use_tool=self._can_use_tool,
            resume=resume_session_id,
            max_turns=max_turns,
            cwd=str(self._sdk_cwd),
            include_partial_messages=True,
            effort=effort,
            thinking=thinking,
            hooks=combined_hooks,
            agents=agents,
            skills=skills,
            setting_sources=["project"],
            # SDK reads the CLI's stdout as one JSON line per message and
            # bails if a single message exceeds this (default 1MB). A Read of
            # a resized geometry render can base64 past 1MB, so lift the cap.
            max_buffer_size=10 * 1024 * 1024,
        )

    async def _on_pre_compact(self, input_data, tool_use_id, context) -> dict:
        await self._emit(StreamEvent("compaction_started", {
            "trigger": input_data.get("trigger", "auto"),
        }))
        return {}

    async def _on_subagent_stop(self, input_data, tool_use_id, context) -> dict:
        """A sub-agent finished. Its intermediate text isn't on the live
        stream, only in its transcript file — `agent_transcript_path` points
        at it. Read the text blocks and emit them for record-only
        persistence (not shown in the UI)."""
        path = input_data.get("agent_transcript_path")
        texts = _extract_subagent_texts(path) if path else []
        if texts:
            await self._emit(StreamEvent("subagent_narration", {
                "agent_id": input_data.get("agent_id"),
                "agent_type": input_data.get("agent_type"),
                "texts": texts,
            }))
        return {}

    async def _can_use_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        ctx: ToolPermissionContext,
    ) -> PermissionResult:
        tool_use_id = ctx.tool_use_id or ""
        agent_id = getattr(ctx, "agent_id", None)

        if _is_ask_user_question(tool_name):
            async with self._gate_lock:
                loop = asyncio.get_running_loop()
                fut: asyncio.Future[PermissionResult] = loop.create_future()
                permissions.register(tool_use_id, fut)
                await self._emit(StreamEvent("question_requested", {
                    "tool_use_id": tool_use_id,
                    "questions": tool_input.get("questions", []),
                    "agent_id": agent_id,
                }))
                try:
                    return await asyncio.wait_for(fut, timeout=_QUESTION_TIMEOUT_S)
                except asyncio.TimeoutError:
                    return PermissionResultAllow(updated_input={
                        "questions": tool_input.get("questions", []),
                        "answers": {},
                        "response": _QUESTION_TIMEOUT_RESPONSE,
                    })
                finally:
                    permissions.unregister(tool_use_id)

        async with self._gate_lock:
            loop = asyncio.get_running_loop()
            fut2: asyncio.Future[PermissionResult] = loop.create_future()
            permissions.register(tool_use_id, fut2)
            await self._emit(StreamEvent("permission_requested", {
                "tool_use_id": tool_use_id,
                "tool": _short_tool_name(tool_name),
                "input": tool_input,
                "agent_id": agent_id,
            }))
            try:
                return await asyncio.wait_for(fut2, timeout=_PERMISSION_TIMEOUT_S)
            except asyncio.TimeoutError:
                return PermissionResultDeny(
                    message="User did not respond in time.",
                    interrupt=False,
                )
            finally:
                permissions.unregister(tool_use_id)

    async def _run(self) -> None:
        """Continuous receive loop for the worker's whole lifetime."""
        assert self._client is not None
        try:
            async for msg in self._client.receive_messages():
                for ev in self._drain_file_events():
                    await self._emit(ev)

                # ── Token-level streaming ──
                if isinstance(msg, SdkStreamEvent):
                    # No turn driving us → the SDK re-invoked the agent on
                    # its own (background-task / Monitor wake-up). Open an
                    # autonomous turn so these events are captured.
                    if not self.turn_active:
                        await self._begin_autonomous_turn()
                    ptu = msg.parent_tool_use_id
                    for ev in _translate_stream_event(msg.event):
                        ev.data["parent_tool_use_id"] = ptu
                        if ev.type == "text_delta":
                            chunk = ev.data.get("content", "")
                            if self._segments is not None:
                                self._segments.add_text_delta(chunk, ptu)
                            if ptu is None:
                                self._assistant_text_parts.append(chunk)
                        elif ev.type == "thinking_started" and self._segments is not None:
                            self._segments.add_thinking_started(ptu)
                        elif ev.type == "thinking_delta" and self._segments is not None:
                            self._segments.add_thinking_delta(ev.data.get("content", ""), ptu)
                        elif ev.type == "tool_started" and self._segments is not None:
                            self._segments.add_tool_started(
                                ev.data.get("id", ""), ev.data.get("tool", ""), ptu,
                            )
                        await self._emit(ev)
                    if msg.session_id:
                        self.sdk_session_id = msg.session_id
                    continue

                # ── Task lifecycle (any time, incl. idle) ──
                if isinstance(msg, TaskStartedMessage):
                    if msg.task_id:
                        self.running_tasks.add(msg.task_id)
                    continue
                if isinstance(msg, TaskNotificationMessage):
                    if msg.task_id:
                        self.running_tasks.discard(msg.task_id)
                    self._notify_state_change()
                    continue

                # ── System info ──
                if isinstance(msg, SystemMessage):
                    if msg.subtype == "init":
                        sid = msg.data.get("session_id")
                        if sid:
                            self.sdk_session_id = sid
                        # Persist the system prompt + config once per session.
                        if not self._config_emitted:
                            self._config_emitted = True
                            await self._emit(StreamEvent(
                                "session_config", dict(self._config_snapshot),
                            ))
                    elif msg.subtype == "compact_boundary":
                        meta = (
                            msg.data.get("compactMetadata")
                            or msg.data.get("compact_metadata")
                            or {}
                        )
                        await self._emit(StreamEvent("compaction_complete", {
                            "trigger": meta.get("trigger"),
                            "pre_tokens": meta.get("preTokens", meta.get("pre_tokens")),
                            "post_tokens": meta.get("postTokens", meta.get("post_tokens")),
                        }))
                    else:
                        # Only log genuine reliability events (retries /
                        # errors) — NOT benign status / task_progress system
                        # messages, which would just be noise.
                        data = msg.data if isinstance(msg.data, dict) else {}
                        subtype = msg.subtype or ""
                        is_retry = "retryAttempt" in data or "retryInMs" in data
                        is_error = "error" in subtype.lower()
                        if is_retry or is_error:
                            await self._emit(StreamEvent("agent_event", {
                                "kind": "retry" if is_retry else "system_error",
                                "data": data,
                            }))
                    continue

                # ── Assistant turn (assembled) ──
                if isinstance(msg, AssistantMessage):
                    # Defensive: open an autonomous turn if the assembled
                    # message arrives before any partial stream event did
                    # (so a wake-up turn is still captured).
                    if not self.turn_active:
                        await self._begin_autonomous_turn()
                    if msg.session_id:
                        self.sdk_session_id = msg.session_id
                    ptu = msg.parent_tool_use_id
                    # Observability: one model_calls row per API response.
                    await self._emit(StreamEvent("model_call", {
                        "model": msg.model,
                        "usage": msg.usage or {},
                        "message_id": msg.message_id,
                        "stop_reason": msg.stop_reason,
                        "parent_tool_use_id": ptu,
                        "error": msg.error,
                    }))
                    if msg.error:
                        await self._emit(StreamEvent("agent_event", {
                            "kind": "api_error",
                            "data": {
                                "error": msg.error,
                                "model": msg.model,
                                "message_id": msg.message_id,
                            },
                        }))
                    persist_needed = False
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            pass  # accumulated from deltas
                        elif isinstance(block, ThinkingBlock):
                            if self._segments is not None:
                                self._segments.add_thinking_text(block.thinking, ptu)
                            await self._emit(StreamEvent("thinking_text", {
                                "content": block.thinking,
                                "parent_tool_use_id": ptu,
                            }))
                            persist_needed = True
                        elif isinstance(block, ToolUseBlock):
                            if self._segments is not None:
                                self._segments.add_tool_input(
                                    block.id, _short_tool_name(block.name),
                                    block.input, ptu,
                                )
                            await self._emit(StreamEvent("tool_input", {
                                "id": block.id,
                                "tool": _short_tool_name(block.name),
                                "input": block.input,
                                "parent_tool_use_id": ptu,
                            }))
                            await self._emit_tool_side_effects(block)
                            persist_needed = True
                    # One checkpoint per message: the AssistantMessage (and
                    # all its blocks, incl. K parallel tool_use calls) arrives
                    # atomically, so a single snapshot captures the lot.
                    if persist_needed:
                        await self._emit_turn_persist()
                    continue

                # ── Tool result ──
                if isinstance(msg, UserMessage):
                    content = msg.content
                    ptu = msg.parent_tool_use_id
                    if isinstance(content, list):
                        saw_output = False
                        for block in content:
                            if isinstance(block, ToolResultBlock):
                                normalized = _normalize_tool_result_content(block.content)
                                if self._segments is not None:
                                    self._segments.add_tool_output(
                                        block.tool_use_id, normalized,
                                        bool(block.is_error), ptu,
                                    )
                                await self._emit(StreamEvent("tool_output", {
                                    "tool_use_id": block.tool_use_id,
                                    "content": normalized,
                                    "is_error": bool(block.is_error),
                                    "parent_tool_use_id": ptu,
                                }))
                                saw_output = True
                        if saw_output:
                            # Tool output is the crash-critical event — a
                            # long tool just finished; checkpoint it now.
                            await self._emit_turn_persist()
                    continue

                # ── End of turn ──
                if isinstance(msg, ResultMessage):
                    if msg.session_id:
                        self.sdk_session_id = msg.session_id
                    await self._finalize_turn(msg)
                    continue
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self._emit(StreamEvent("error", {
                "message": f"{type(e).__name__}: {e}",
                "recoverable": False,
            }))
            # Unblock any waiting turn, then release ownership.
            await self._emit(StreamEvent("turn_complete", {"stop_reason": "error"}))
            if self._turn_out is not None:
                await self._turn_out.put(_TURN_END)
            self._end_turn()

    async def _emit_tool_side_effects(self, block: ToolUseBlock) -> None:
        """The approval / spec / phase-advance SSE events keyed off tool calls."""
        name = block.name
        if _is_present_spec(name):
            spec_path = block.input.get("specification_path", "")
            try:
                markdown = Path(spec_path).read_text(encoding="utf-8")
            except Exception:
                markdown = ""
            await self._emit(StreamEvent("specification_presented", {
                "markdown": markdown,
            }))
        elif _is_subtask_approval(name) or _is_mesh_approval(name):
            await self._emit(StreamEvent("subtask_approval_requested", {}))
        elif _is_experiment_approval(name):
            await self._emit(StreamEvent("experiment_approval_requested", {}))
        elif _is_phase_advance(name):
            await self._emit(StreamEvent("phase_advance_requested", {}))

    async def _finalize_turn(self, msg: ResultMessage) -> None:
        # Mirror run_turn's terminal handling: emit assistant_turn (for
        # persistence), sdk_session_id, turn_complete, then unblock the
        # turn consumer with the sentinel. An interrupted turn arrives
        # with is_error=True but we initiated it, so suppress the error.
        if msg.is_error and not self._interrupted:
            await self._emit(StreamEvent("error", {
                "message": msg.result or msg.subtype or "agent error",
                "recoverable": False,
            }))

        full_text = "".join(self._assistant_text_parts).strip()
        segs = self._segments.segments if self._segments is not None else []
        if full_text or segs:
            await self._emit(StreamEvent("assistant_turn", {
                "text": full_text,
                "segments": segs,
            }))
        if self.sdk_session_id:
            await self._emit(StreamEvent("sdk_session_id", {
                "session_id": self.sdk_session_id,
            }))
        stop_reason = "interrupted" if self._interrupted else (msg.stop_reason or msg.subtype)
        await self._emit(StreamEvent("turn_complete", {
            "stop_reason": stop_reason,
        }))
        # Unblock the (possibly-disconnected) consumer first, then release
        # turn ownership — which fires the close-check.
        if self._turn_out is not None:
            await self._turn_out.put(_TURN_END)
        self._end_turn()
