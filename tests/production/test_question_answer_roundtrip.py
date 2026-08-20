"""AskUserQuestion answer round-trip.

The HTTP route in `src.api.routes.submit_question_answer` and the
`can_use_tool` callback in `src.agent.session_manager.SessionWorker` meet
through the same module-level Future registry in `src.agent.permissions` that the
permission flow uses. `AskUserQuestion` differs in one way: the answer
is returned by resolving the Future with an Allow whose `updated_input`
carries the user's selections, which the SDK then runs the tool with.

These tests exercise that meeting point — register a Future, resolve it
the way the question route would, confirm the awaiting side gets an
Allow with the expected `updated_input` payload.
"""

import asyncio

import pytest
from claude_agent_sdk import PermissionResultAllow

from src.agent import permissions


_QUESTIONS = [
    {
        "question": "Which turbulence model?",
        "header": "Turbulence",
        "options": [
            {"label": "k-omega SST", "description": "Adverse pressure gradients"},
            {"label": "k-epsilon", "description": "Free-shear flows"},
        ],
        "multiSelect": False,
    }
]


@pytest.mark.asyncio
async def test_resolve_answers_unblocks_with_allow_and_payload():
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    permissions.register("q-1", fut)

    answers = {"Which turbulence model?": "k-omega SST"}
    assert permissions.resolve_answers("q-1", _QUESTIONS, answers) is True

    result = await fut
    assert isinstance(result, PermissionResultAllow)
    # The SDK needs both the echoed questions and the answers map.
    assert result.updated_input["questions"] == _QUESTIONS
    assert result.updated_input["answers"] == answers
    # No `response` key unless one was passed.
    assert "response" not in result.updated_input

    permissions.unregister("q-1")


@pytest.mark.asyncio
async def test_resolve_answers_carries_optional_response():
    # The timeout path (and a future "answer in chat" path) resolves with
    # an empty answers map plus a freeform `response` that supersedes it.
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    permissions.register("q-2", fut)

    assert permissions.resolve_answers(
        "q-2", _QUESTIONS, {}, response="Use your best judgment."
    ) is True

    result = await fut
    assert isinstance(result, PermissionResultAllow)
    assert result.updated_input["answers"] == {}
    assert result.updated_input["response"] == "Use your best judgment."

    permissions.unregister("q-2")


@pytest.mark.asyncio
async def test_resolve_answers_preserves_multiselect_and_other_text():
    # multiSelect answers arrive as a list; an "Other" choice arrives as
    # the typed text (not the word "Other"). The registry passes both
    # through verbatim — it doesn't interpret the answer shape.
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    permissions.register("q-3", fut)

    answers = {"Which outputs?": ["Drag coefficient", "wall shear stress"]}
    assert permissions.resolve_answers("q-3", _QUESTIONS, answers) is True

    result = await fut
    assert result.updated_input["answers"]["Which outputs?"] == [
        "Drag coefficient",
        "wall shear stress",
    ]

    permissions.unregister("q-3")


def test_resolve_answers_unknown_id_returns_false():
    # Stale submit after the SSE stream was cancelled — the route must
    # distinguish this from a successful resolve so it can 404.
    assert permissions.resolve_answers("never-registered", _QUESTIONS, {}) is False


@pytest.mark.asyncio
async def test_resolve_answers_already_resolved_is_noop():
    # Race between the HTTP submit and the can_use_tool timeout: the
    # second resolve must be a no-op so the first wins and we never hit
    # InvalidStateError on the underlying Future.
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    permissions.register("q-4", fut)

    assert permissions.resolve_answers("q-4", _QUESTIONS, {"x": "y"}) is True
    assert permissions.resolve_answers("q-4", _QUESTIONS, {"x": "z"}) is False

    result = await fut
    assert result.updated_input["answers"] == {"x": "y"}

    permissions.unregister("q-4")
