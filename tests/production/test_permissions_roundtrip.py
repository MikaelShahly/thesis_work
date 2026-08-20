"""Permission registry round-trip.

The HTTP route in `src.api.routes.submit_permission_decision` and the
`can_use_tool` callback in `src.agent.session_manager.SessionWorker` meet
through the module-level Future registry in `src.agent.permissions`. These tests
exercise the meeting point — register a Future, resolve it the way the
HTTP route would, confirm the awaiting side gets the right result.

This is the production path because it's what really happens at
runtime (minus the SDK subprocess and the FastAPI request wrapper);
the only thing we mock here is the network hop.
"""

import asyncio

import pytest
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from src.agent import permissions


@pytest.mark.asyncio
async def test_resolve_allow_unblocks_with_allow_result():
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    permissions.register("tool-use-1", fut)

    assert permissions.resolve_allow("tool-use-1") is True
    result = await fut
    assert isinstance(result, PermissionResultAllow)

    permissions.unregister("tool-use-1")


@pytest.mark.asyncio
async def test_resolve_deny_unblocks_with_canonical_message():
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    permissions.register("tool-use-2", fut)

    assert permissions.resolve_deny("tool-use-2") is True
    result = await fut
    assert isinstance(result, PermissionResultDeny)
    assert result.message == permissions.DENY_MESSAGE
    assert result.interrupt is False

    permissions.unregister("tool-use-2")


def test_resolve_unknown_id_returns_false():
    # Stale click after the SSE stream was cancelled — the route
    # should distinguish this from a successful resolve so it can 404.
    assert permissions.resolve_allow("never-registered") is False
    assert permissions.resolve_deny("never-registered") is False


@pytest.mark.asyncio
async def test_already_resolved_future_does_not_double_resolve():
    # Race between the HTTP click and the can_use_tool timeout: both
    # could reach the registry. The second resolve must be a no-op so
    # the first decision wins and we never hit InvalidStateError on
    # the underlying Future.
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    permissions.register("tool-use-3", fut)

    assert permissions.resolve_allow("tool-use-3") is True
    assert permissions.resolve_deny("tool-use-3") is False  # already done

    result = await fut
    assert isinstance(result, PermissionResultAllow)

    permissions.unregister("tool-use-3")
