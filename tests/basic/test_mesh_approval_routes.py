"""HTTP-level checks on the `/approve-mesh-step` endpoint.

Drives the FastAPI app through TestClient against a real on-disk
project (DB + folders) materialised inside `tmp_path`. The agent
itself is not invoked — `run_mesh_turn` is monkeypatched to a no-op
async generator so we can confirm:

- `/approve-mesh-step` clears `approval_pending` + `approval_kind`
  without touching `phase`, and streams a `mesh_step_approved` event
  before the (mocked) agent turn.
- The endpoint 400s when invoked from the wrong phase.

The mesh → improver phase advance now goes through the unified
`/approve-phase-advance` endpoint — see
[test_phase_advance_route.py](tests/basic/test_phase_advance_route.py).
"""

from __future__ import annotations

import importlib
import json
import sys
from typing import AsyncIterator

import pytest
from fastapi.testclient import TestClient


async def _noop_mesh_turn(**kwargs) -> AsyncIterator[None]:
    """Drop-in replacement for `run_mesh_turn` that yields nothing.

    Keeps the route's `async for ev in run_mesh_turn(...)` loop intact
    while skipping the SDK round-trip. The `if False: yield` is the
    canonical empty-async-generator shape — the function still
    qualifies as an async generator (so the type matches what the
    route expects) but never produces an event.
    """
    if False:
        yield None  # pragma: no cover


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """Spin up the app against a tmp DB + tmp projects/ root.

    Mirrors the canonical pattern from
    [test_geometry_upload.py](tests/basic/test_geometry_upload.py).
    """
    db_path = tmp_path / "agenticcfd.db"
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    import src.config as config

    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "PROJECTS_DIR", projects_dir)

    for mod in ("src.db", "src.api.routes", "src.api.app"):
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])

    from src.api.app import app
    import src.api.routes as routes

    # Replace the mesh handler so /approve-mesh-step doesn't invoke
    # the SDK. The route's `async for ev in run_mesh_turn(...)` loop
    # just sees an empty stream.
    monkeypatch.setattr(routes, "run_mesh_turn", _noop_mesh_turn)

    with TestClient(app) as client:
        yield client


def _create_project(client: TestClient, name: str = "Mesh Test Project") -> dict:
    res = client.post("/api/projects", json={"name": name})
    assert res.status_code == 200, res.text
    return res.json()


def _put_project_into_mesh_phase(project_id: str) -> None:
    """Skip past simulation_spec / case_builder for the routes-under-test.

    The mesh approval endpoints only care about the project's current
    phase and the approval flags; the messages/sessions that would
    normally precede mesh aren't relevant here.
    """
    import src.db as db

    db.create_session(project_id, "mesh")
    db.update_project(
        project_id,
        phase="mesh",
        approval_pending=1,
        approval_kind="mesh_step",
    )


def _project_row(project_id: str) -> dict:
    import src.db as db

    row = db.get_project(project_id)
    assert row is not None
    return row


# ── /approve-mesh-step ─────────────────────────────────────────────────
def test_approve_mesh_step_clears_pending_without_touching_phase(
    app_client: TestClient,
):
    project = _create_project(app_client)
    _put_project_into_mesh_phase(project["id"])

    # Consume the SSE response. The route streams a single
    # `mesh_step_approved` event and then exits (the mocked
    # `run_mesh_turn` yields nothing).
    with app_client.stream(
        "POST", f"/api/projects/{project['id']}/approve-mesh-step",
    ) as res:
        assert res.status_code == 200
        body = "".join(res.iter_text())

    assert "mesh_step_approved" in body
    # The streamed event payload carries the auto_resumed flag so the
    # frontend knows the agent loop will resume on the same channel.
    payload_line = next(
        line for line in body.splitlines() if line.startswith("data:")
    )
    payload = json.loads(payload_line.removeprefix("data:").strip())
    assert payload["status"] == "approved"
    assert payload["auto_resumed"] is True

    row = _project_row(project["id"])
    # Sub-step approval does NOT advance the phase.
    assert row["phase"] == "mesh"
    # And it clears the approval flags so the pill / panel come down.
    assert row["approval_pending"] == 0
    assert row["approval_kind"] is None


def test_approve_mesh_step_rejects_wrong_phase(app_client: TestClient):
    project = _create_project(app_client)
    # Default phase is simulation_spec — never mesh.
    res = app_client.post(
        f"/api/projects/{project['id']}/approve-mesh-step",
    )
    assert res.status_code == 400, res.text
    assert "simulation_spec" in res.json()["detail"]


def test_approve_mesh_step_404s_unknown_project(app_client: TestClient):
    res = app_client.post(
        "/api/projects/nonexistent-id/approve-mesh-step",
    )
    assert res.status_code == 404
