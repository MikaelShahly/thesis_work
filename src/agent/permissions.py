"""Pending tool-permission decisions.

`can_use_tool` (in `src.agent.core`) creates a Future and registers it
here keyed by `tool_use_id`, then awaits the Future. The HTTP route in
`src.api.routes` looks the Future up and resolves it with an
`PermissionResultAllow` or `PermissionResultDeny`.

The registry is module-level — the SDK callback and the HTTP handler
both run inside the same single-process FastAPI worker, and SDK
`tool_use_id` values are UUIDs (collision-free), so we don't bother
namespacing by project/session.

Lifecycle: callback registers → either the HTTP route resolves the
Future, or the callback's `wait_for` hits the timeout. In both cases
the callback's `finally` block unregisters. The HTTP route never
removes entries — that's the callback's job.
"""

from __future__ import annotations

import asyncio
from claude_agent_sdk import (
    PermissionResult,
    PermissionResultAllow,
    PermissionResultDeny,
)


# Reason string the agent sees when the user clicks Deny. Kept short so
# the model doesn't fixate on it but explicit enough to discourage a
# blind retry of the same command.
DENY_MESSAGE = (
    "User denied this action. Don't retry the same command, try a "
    "different approach."
)


_pending: dict[str, asyncio.Future[PermissionResult]] = {}


def register(tool_use_id: str, future: asyncio.Future[PermissionResult]) -> None:
    _pending[tool_use_id] = future


def unregister(tool_use_id: str) -> None:
    _pending.pop(tool_use_id, None)


def resolve_allow(tool_use_id: str) -> bool:
    """Resolve the pending Future as an unconditional Allow.

    Returns True if a Future was found and resolved, False otherwise
    (no such id, or the Future was already done — e.g. raced with the
    timeout in `can_use_tool`).
    """
    return _resolve(tool_use_id, PermissionResultAllow())


def resolve_deny(tool_use_id: str) -> bool:
    """Resolve the pending Future as a Deny with the canonical message."""
    return _resolve(
        tool_use_id,
        PermissionResultDeny(message=DENY_MESSAGE, interrupt=False),
    )


def resolve_deny_with_feedback(tool_use_id: str, message: str) -> bool:
    """Deny but pass the user's own text as the reason.

    The model sees `message` verbatim in place of the canned DENY_MESSAGE,
    so the user can correct course without first interrupting the turn.
    `interrupt=False` keeps the agent running — it just picks back up on
    the same loop with the user's reason in hand.
    """
    return _resolve(
        tool_use_id,
        PermissionResultDeny(message=message, interrupt=False),
    )


def resolve_answers(
    tool_use_id: str,
    questions: list,
    answers: dict,
    response: str | None = None,
) -> bool:
    """Resolve a paused AskUserQuestion call with the user's selections.

    The SDK runs the tool with `updated_input`, so we echo the original
    `questions` (required for the tool to process) plus the `answers`
    map (question text → chosen label / list of labels / free text). An
    optional `response` carries a freeform reply that supersedes the
    per-question answers when set.

    Returns True if a Future was found and resolved, False otherwise.
    """
    payload: dict = {"questions": questions, "answers": answers}
    if response is not None:
        payload["response"] = response
    return _resolve(tool_use_id, PermissionResultAllow(updated_input=payload))


def _resolve(tool_use_id: str, result: PermissionResult) -> bool:
    fut = _pending.get(tool_use_id)
    if fut is None or fut.done():
        return False
    fut.set_result(result)
    return True
