"""Permission deny-with-feedback resolves the Future with user text.

The HTTP route at `/permission/{id}/deny-feedback` calls
`permissions.resolve_deny_with_feedback`, which is expected to produce
a `PermissionResultDeny` whose `message` is the user's typed text
verbatim — *not* the canned DENY_MESSAGE. This is what allows the user
to correct the agent without first interrupting the whole turn.
"""

from __future__ import annotations

import asyncio

import pytest
from claude_agent_sdk import PermissionResultDeny

from src.agent import permissions


@pytest.fixture(autouse=True)
def _clear_pending():
    permissions._pending.clear()
    yield
    permissions._pending.clear()


def test_resolves_with_user_message_verbatim():
    user_text = "Run from the project root, not from Case/."

    async def _run() -> PermissionResultDeny:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        permissions.register("tu-1", fut)
        ok = permissions.resolve_deny_with_feedback("tu-1", user_text)
        assert ok is True
        return await fut

    result = asyncio.run(_run())
    assert isinstance(result, PermissionResultDeny)
    assert result.message == user_text
    # Must NOT trip the heavy `interrupt=True` switch — that would stop
    # the whole turn. Deny-with-feedback is a course-correction inside
    # the loop, not a halt.
    assert result.interrupt is False
    # Must not silently fall back to the canned text.
    assert result.message != permissions.DENY_MESSAGE


def test_returns_false_when_no_pending_future():
    assert permissions.resolve_deny_with_feedback("missing", "anything") is False


def test_does_not_resolve_a_done_future():
    # Mirror the race the canonical resolve path guards against: the
    # callback's `wait_for` already timed out; we must not blow up
    # resolving a done Future.
    async def _run():
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        permissions.register("tu-2", fut)
        fut.set_result(PermissionResultDeny(message="already", interrupt=False))
        return permissions.resolve_deny_with_feedback("tu-2", "new")

    assert asyncio.run(_run()) is False
