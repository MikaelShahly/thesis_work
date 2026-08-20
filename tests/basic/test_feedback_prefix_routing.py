"""Feedback-prefix detection on the /messages route.

`[Feedback]:` (the phase-agnostic phase-advance prefix, used by
case_builder / mesh / improver phase-advance) and `[Feedback on mesh]:`
(mesh sub-step) both clear `approval_pending` + `approval_kind` so the
UI exits pending state on reload. Non-feedback messages don't touch
those flags.

The phase handlers themselves are monkeypatched to no-op async
generators so the route's side effects on the DB are observable
without invoking the SDK.
"""

from __future__ import annotations

import importlib
import sys
from typing import AsyncIterator

import pytest
from fastapi.testclient import TestClient


async def _noop_handler(**kwargs) -> AsyncIterator[None]:
    if False:
        yield None  # pragma: no cover


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

    from src.api.app import app
    import src.api.routes as routes

    # Replace every phase handler so /messages doesn't reach the SDK.
    # The route's side effects (approval_pending clearing on the
    # feedback prefix) happen BEFORE the handler is called, so they
    # remain observable.
    routes.PHASE_HANDLERS["simulation_spec"] = _noop_handler
    routes.PHASE_HANDLERS["case_builder"] = _noop_handler
    routes.PHASE_HANDLERS["mesh"] = _noop_handler

    with TestClient(app) as client:
        yield client


def _create_project(client: TestClient) -> dict:
    res = client.post("/api/projects", json={"name": "Feedback Test"})
    assert res.status_code == 200, res.text
    return res.json()


def _put_project_into_phase(project_id: str, phase: str) -> None:
    import src.db as db

    db.create_session(project_id, phase)
    kind_for_phase = {
        "case_builder": "case_builder_phase_advance",
        "mesh": "mesh_step",
    }
    db.update_project(
        project_id,
        phase=phase,
        approval_pending=1,
        approval_kind=kind_for_phase.get(phase),
    )


def _project_row(project_id: str) -> dict:
    import src.db as db

    row = db.get_project(project_id)
    assert row is not None
    return row


def _drain(client: TestClient, project_id: str, content: str) -> None:
    """POST a message and consume the SSE stream so the route's
    finally-block runs and DB writes flush before we inspect."""
    with client.stream(
        "POST",
        f"/api/projects/{project_id}/messages",
        json={"content": content},
    ) as res:
        assert res.status_code == 200, res.read().decode()
        # Drain the (empty) stream so the route handler exits cleanly.
        list(res.iter_text())


# ── case_builder: phase-agnostic [Feedback]: prefix ────────────────────
def test_case_feedback_prefix_clears_approval_pending(app_client: TestClient):
    # case_builder's only approval gate is request_phase_advance, so its
    # feedback arrives with the phase-agnostic [Feedback]: prefix.
    project = _create_project(app_client)
    _put_project_into_phase(project["id"], "case_builder")
    assert _project_row(project["id"])["approval_pending"] == 1

    _drain(
        app_client,
        project["id"],
        "[Feedback]: please drop the inlet refinement",
    )

    row = _project_row(project["id"])
    assert row["approval_pending"] == 0
    assert row["approval_kind"] is None


# ── mesh: new behaviour ────────────────────────────────────────────────
def test_mesh_feedback_prefix_clears_approval_pending(app_client: TestClient):
    project = _create_project(app_client)
    _put_project_into_phase(project["id"], "mesh")
    assert _project_row(project["id"])["approval_pending"] == 1
    assert _project_row(project["id"])["approval_kind"] == "mesh_step"

    _drain(
        app_client,
        project["id"],
        "[Feedback on mesh]: layers near patch wing look too thin",
    )

    row = _project_row(project["id"])
    assert row["approval_pending"] == 0
    assert row["approval_kind"] is None


def test_mesh_plain_message_keeps_approval_pending(app_client: TestClient):
    # A plain message during approval is a *question*, not feedback —
    # the pill stays up so the user can approve from the UI after the
    # answer.
    project = _create_project(app_client)
    _put_project_into_phase(project["id"], "mesh")

    _drain(
        app_client,
        project["id"],
        "Where is the surface feature extraction running?",
    )

    row = _project_row(project["id"])
    assert row["approval_pending"] == 1
    assert row["approval_kind"] == "mesh_step"


def test_case_prefix_in_mesh_phase_does_not_clear(app_client: TestClient):
    # Prefix matching is phase-scoped. A user typing `[Feedback on
    # case]:` while in the mesh phase should not clear the mesh
    # approval — the prefix has no semantic meaning here.
    project = _create_project(app_client)
    _put_project_into_phase(project["id"], "mesh")

    _drain(
        app_client,
        project["id"],
        "[Feedback on case]: this is the wrong phase",
    )

    row = _project_row(project["id"])
    assert row["approval_pending"] == 1
    assert row["approval_kind"] == "mesh_step"


def test_mesh_prefix_in_case_phase_does_not_clear(app_client: TestClient):
    # Symmetric: `[Feedback on mesh]:` in case_builder is just user
    # text, not a feedback gesture. (case_builder only recognises the
    # phase-agnostic `[Feedback]:` prefix.)
    project = _create_project(app_client)
    _put_project_into_phase(project["id"], "case_builder")

    _drain(
        app_client,
        project["id"],
        "[Feedback on mesh]: typed early — case approval still pending",
    )

    row = _project_row(project["id"])
    assert row["approval_pending"] == 1
    assert row["approval_kind"] == "case_builder_phase_advance"
