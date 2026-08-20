"""HTTP-level checks on `DELETE /projects/{id}`.

Deletion must clean up three things: the live worker (out of scope here —
no worker is started), the project's files on disk, and every DB row that
hangs off the project. It must also tell the caller whether the live
ParaView bridge was bound to the deleted project, so the frontend can ask
the user to close that window (we never kill it for them).
"""

from __future__ import annotations

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

    from src.api.app import app

    with TestClient(app) as client:
        yield client


def _create_project(client: TestClient, name: str = "Delete Test") -> dict:
    res = client.post("/api/projects", json={"name": name})
    assert res.status_code == 200, res.text
    return res.json()


def test_delete_missing_project_404(app_client: TestClient):
    res = app_client.delete("/api/projects/does-not-exist")
    assert res.status_code == 404


def test_delete_removes_files_and_all_db_rows(app_client: TestClient):
    import src.db as db

    project = _create_project(app_client)
    pid = project["id"]

    # Hang one row off every child table (mirrors the cascade chain
    # projects → sessions → {messages → message_segments, model_calls,
    # session_config, agent_events, subagent_narration}).
    sid = db.create_session(pid, "mesh")
    mid = db.save_message(sid, "user", "hello")
    with db._conn() as c:
        c.execute(
            "INSERT INTO message_segments (id, message_id, seq, kind, content) "
            "VALUES (?,?,?,?,?)",
            ("seg1", mid, 0, "text", "x"),
        )
        c.execute(
            "INSERT INTO model_calls (id, session_id, model) VALUES (?,?,?)",
            ("mc1", sid, "claude-opus-4-8"),
        )
        c.execute(
            "INSERT INTO session_config (session_id, system_prompt) VALUES (?,?)",
            (sid, "sys"),
        )
        c.execute(
            "INSERT INTO agent_events (id, session_id, kind, data) VALUES (?,?,?,?)",
            ("ev1", sid, "retry", "{}"),
        )
        c.execute(
            "INSERT INTO subagent_narration (id, session_id, agent_id, seq, content) "
            "VALUES (?,?,?,?,?)",
            ("na1", sid, "a1", 0, "n"),
        )

    from src.api.routes import _project_dir

    proj_dir = _project_dir(db.get_project(pid))
    assert proj_dir.exists()

    res = app_client.delete(f"/api/projects/{pid}")
    assert res.status_code == 200, res.text

    # Files gone.
    assert not proj_dir.exists()

    # Every table empty — the cascade fired (PRAGMA foreign_keys = ON).
    tables = [
        "projects", "sessions", "messages", "message_segments",
        "model_calls", "session_config", "agent_events", "subagent_narration",
    ]
    with db._conn() as c:
        for t in tables:
            n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            assert n == 0, f"{t} not cleaned up: {n} rows remain"


def test_delete_reports_paraview_attached_false_when_no_bridge(app_client: TestClient):
    project = _create_project(app_client)
    res = app_client.delete(f"/api/projects/{project['id']}")
    assert res.status_code == 200, res.text
    assert res.json()["paraview_attached"] is False


def test_delete_reports_paraview_attached_when_bound(app_client: TestClient, monkeypatch):
    project = _create_project(app_client)
    pid = project["id"]

    # Pretend the live bridge is bound to this project.
    import src.api.routes as routes

    monkeypatch.setattr(
        routes.paraview_lifecycle, "current_project", lambda: (pid, "Delete Test")
    )

    res = app_client.delete(f"/api/projects/{pid}")
    assert res.status_code == 200, res.text
    assert res.json()["paraview_attached"] is True
