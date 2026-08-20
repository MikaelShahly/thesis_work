"""HTTP-level checks for /interrupt and /permission/{id}/deny-feedback.

The actual SDK / agent loop isn't invoked — these tests confirm the
two new endpoints validate their input and route through to the
registry / permissions modules correctly. End-to-end behaviour (real
SDK interrupt, real partial-text persistence) belongs in
`tests/production/` once we have an SDK-backed harness.
"""

from __future__ import annotations

import asyncio
import importlib
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    db_path = tmp_path / "agenticcfd.db"
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    import src.config as config

    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "PROJECTS_DIR", projects_dir)

    for mod in ("src.db", "src.api.routes", "src.api.app"):
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])

    # Always start with an empty session registry to avoid cross-
    # test bleed-through (it's module-level).
    from src.agent import session_registry

    session_registry._workers.clear()

    from src.api.app import app

    with TestClient(app) as client:
        yield client

    session_registry._workers.clear()


def _create_project(client: TestClient, name: str = "Interrupt Test") -> dict:
    res = client.post("/api/projects", json={"name": name})
    assert res.status_code == 200, res.text
    return res.json()


# ── /interrupt ─────────────────────────────────────────────────────────
def test_interrupt_returns_false_when_no_active_run(app_client: TestClient):
    project = _create_project(app_client)
    res = app_client.post(f"/api/projects/{project['id']}/interrupt")
    assert res.status_code == 200
    # No turn was in flight; route is idempotent and tells the client
    # the no-op shape.
    assert res.json() == {"interrupted": False}


def test_interrupt_404s_for_unknown_project(app_client: TestClient):
    res = app_client.post("/api/projects/does-not-exist/interrupt")
    assert res.status_code == 404


def test_interrupt_returns_true_when_run_is_active(app_client: TestClient):
    project = _create_project(app_client)

    # Register a fake worker for this project to simulate an in-flight
    # turn. The route routes through session_registry.interrupt_project,
    # which finds the worker by project_id and calls .interrupt() on it.
    class _FakeWorker:
        def __init__(self, project_id):
            self.project_id = project_id
            self.interrupted = 0

        async def interrupt(self):
            self.interrupted += 1

    fake = _FakeWorker(project["id"])
    from src.agent import session_registry

    session_registry._workers[f"{project['id']}:case_builder"] = fake

    res = app_client.post(f"/api/projects/{project['id']}/interrupt")
    assert res.status_code == 200
    assert res.json() == {"interrupted": True}
    assert fake.interrupted == 1


# ── /permission/{id}/deny-feedback ─────────────────────────────────────
def test_deny_feedback_404s_for_unknown_tool_use_id(app_client: TestClient):
    project = _create_project(app_client)
    res = app_client.post(
        f"/api/projects/{project['id']}/permission/no-such-id/deny-feedback",
        json={"message": "anything"},
    )
    assert res.status_code == 404


def test_deny_feedback_404s_for_unknown_project(app_client: TestClient):
    res = app_client.post(
        "/api/projects/missing/permission/whatever/deny-feedback",
        json={"message": "hi"},
    )
    assert res.status_code == 404


def test_deny_feedback_rejects_empty_message(app_client: TestClient):
    project = _create_project(app_client)
    res = app_client.post(
        f"/api/projects/{project['id']}/permission/x/deny-feedback",
        json={"message": ""},
    )
    # Pydantic min_length=1 enforces this — 422 is FastAPI's validation
    # failure shape.
    assert res.status_code == 422


def test_deny_feedback_resolves_pending_future_with_user_text(
    app_client: TestClient,
):
    from claude_agent_sdk import PermissionResultDeny

    from src.agent import permissions

    project = _create_project(app_client)

    # Use a single event loop for the whole test so the Future, the
    # route handler, and the `await fut` all share the same loop —
    # cross-loop futures break.
    async def _drive():
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        permissions.register("tu-route", fut)

        # Driving the FastAPI app from inside an async context: use
        # asyncio.to_thread so the sync TestClient call doesn't block
        # the loop the Future is waiting on.
        res = await asyncio.to_thread(
            app_client.post,
            f"/api/projects/{project['id']}/permission/tu-route/deny-feedback",
            json={"message": "Don't use Bash here, prefer Edit."},
        )
        assert res.status_code == 200
        return await fut

    try:
        result = asyncio.run(_drive())
        assert isinstance(result, PermissionResultDeny)
        assert result.message == "Don't use Bash here, prefer Edit."
        assert result.interrupt is False
    finally:
        permissions._pending.clear()
