"""HTTP-level checks on the unified `/approve-phase-advance` SSE endpoint.

`request_phase_advance` is the single phase-completion gate for every
agent phase, so one endpoint handles all three transitions:
case_builder → mesh → improver → post_process.

The handoff doc + updated spec are written by the agent BEFORE it calls
`request_phase_advance`, so this route advances directly — there is no
handoff turn and no commit step. On the user's approval it:

- emits `phase_approved` (UI clears the pill) and `phase_transitioned`
  (the divider, live-only for the first subscriber),
- flips `projects.phase` to the downstream phase and clears the
  approval flags,
- creates a new session for the downstream phase, then fires that
  phase's kickoff turn on the same buffered stream.

The downstream agent turn is resolved via `PHASE_HANDLERS[phase_to]`
and stubbed here with a no-op async generator so the SSE stream drains
without touching the SDK.
"""

from __future__ import annotations

import importlib
import json
import sys
from typing import AsyncIterator

import pytest
from fastapi.testclient import TestClient


async def _noop_turn(**kwargs) -> AsyncIterator[None]:
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

    # The downstream kickoff turn runs inside this route via
    # PHASE_HANDLERS[phase_to] — stub every downstream phase so the SSE
    # generator drains without touching the SDK.
    for phase in ("mesh", "improver", "post_process"):
        monkeypatch.setitem(routes.PHASE_HANDLERS, phase, _noop_turn)

    with TestClient(app) as client:
        yield client


def _create_project(client: TestClient, name: str = "Advance Test Project") -> dict:
    res = client.post("/api/projects", json={"name": name})
    assert res.status_code == 200, res.text
    return res.json()


def _put_project_into_phase(project_id: str, phase: str) -> None:
    """Skip straight to `phase` with an active session + a pending pill.

    The route only checks the phase and that a current session exists
    (it resumes nothing — the downstream session is fresh).
    """
    import src.db as db

    db.create_session(project_id, phase)
    db.update_project(
        project_id,
        phase=phase,
        approval_pending=1,
        approval_kind=f"{phase}_phase_advance",
    )


def _project_row(project_id: str) -> dict:
    import src.db as db

    row = db.get_project(project_id)
    assert row is not None
    return row


def _sse_events(body: str) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    normalised = body.replace("\r\n", "\n")
    for chunk in normalised.split("\n\n"):
        name = None
        data = None
        for line in chunk.splitlines():
            if line.startswith("event:"):
                name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                raw = line.removeprefix("data:").strip()
                data = json.loads(raw) if raw else {}
        if name is not None:
            out.append((name, data or {}))
    return out


# Every transition the single gate handles: (from_phase, to_phase).
_TRANSITIONS = [
    ("case_builder", "mesh"),
    ("mesh", "improver"),
    ("improver", "post_process"),
]


@pytest.mark.parametrize("phase_from,phase_to", _TRANSITIONS)
def test_approve_advances_phase_directly(
    app_client: TestClient, phase_from: str, phase_to: str,
):
    project = _create_project(app_client)
    _put_project_into_phase(project["id"], phase_from)

    with app_client.stream(
        "POST", f"/api/projects/{project['id']}/approve-phase-advance",
    ) as res:
        assert res.status_code == 200, res.text
        body = "".join(res.iter_text())

    events = _sse_events(body)
    names = [name for name, _ in events]

    # Both the pill-clearing ack and the divider reach the first
    # subscriber (the buffer holds the live-only divider for it).
    assert "phase_approved" in names
    assert "phase_transitioned" in names

    transition = next(d for n, d in events if n == "phase_transitioned")
    assert transition["phase_from"] == phase_from
    assert transition["phase_to"] == phase_to
    # The advance is always direct now — no safety-net auto-advance flag.
    assert "auto_advanced" not in transition
    # The downstream kickoff always follows on the same stream — the
    # reducer reads this to keep `streaming: true` across the divider.
    assert transition["downstream_agent_starting"] is True

    row = _project_row(project["id"])
    assert row["phase"] == phase_to
    assert row["approval_pending"] == 0
    assert row["approval_kind"] is None

    import src.db as db
    sessions = db.list_sessions(project["id"])
    assert any(s["phase"] == phase_to for s in sessions)


def test_approve_rejects_wrong_phase(app_client: TestClient):
    project = _create_project(app_client)
    # Default phase is simulation_spec — not a phase-advance source.
    res = app_client.post(f"/api/projects/{project['id']}/approve-phase-advance")
    assert res.status_code == 400, res.text
    assert "simulation_spec" in res.json()["detail"]


def test_approve_rejects_terminal_phase(app_client: TestClient):
    project = _create_project(app_client)
    _put_project_into_phase(project["id"], "post_process")
    res = app_client.post(f"/api/projects/{project['id']}/approve-phase-advance")
    assert res.status_code == 400, res.text
    assert "post_process" in res.json()["detail"]


def test_approve_404s_unknown_project(app_client: TestClient):
    res = app_client.post("/api/projects/nonexistent-id/approve-phase-advance")
    assert res.status_code == 404
