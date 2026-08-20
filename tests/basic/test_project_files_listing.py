"""GET /api/projects/{id}/files — folder discovery semantics.

The endpoint pre-seeds the five blessed folders (Specification, Case,
Mesh, Reports, Geometry) so they always appear in the response, even
empty. Beyond that, it scans the project root and surfaces any
additional top-level folder the agent (or user) has created — that's
how agent-spawned scratch / log / diagnostic directories reach the
sidebar tree.
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


def _create_project(client: TestClient) -> dict:
    res = client.post("/api/projects", json={"name": "discovery-test"})
    assert res.status_code == 200, res.text
    return res.json()


def _project_dir(tmp_path, project):
    return tmp_path / "projects" / project["folder_name"]


def test_blessed_subfolders_are_always_present(app_client, tmp_path):
    project = _create_project(app_client)
    tree = app_client.get(f"/api/projects/{project['id']}/files").json()
    for sub in ("Specification", "Geometry", "Cases", "handoffs"):
        assert sub in tree, f"blessed subfolder {sub!r} missing from /files response"
        assert tree[sub] == [], f"blessed subfolder {sub!r} should start empty"


def test_agent_created_top_level_folder_appears_in_listing(app_client, tmp_path):
    # Simulates an agent doing `mkdir -p Diagnostics && echo … > Diagnostics/run.log`
    # via its Bash tool — anything at the project root that isn't a
    # blessed folder must still surface.
    project = _create_project(app_client)
    proj_dir = _project_dir(tmp_path, project)

    extra = proj_dir / "Diagnostics"
    extra.mkdir()
    (extra / "run.log").write_text("mesh quality check: ok\n")

    tree = app_client.get(f"/api/projects/{project['id']}/files").json()

    assert "Diagnostics" in tree, (
        f"agent-created folder not surfaced in /files; keys were {list(tree)}"
    )
    paths = [entry["path"] for entry in tree["Diagnostics"]]
    assert "Diagnostics/run.log" in paths


def test_hidden_top_level_folder_is_skipped(app_client, tmp_path):
    # `.paraview_snapshots/` and friends are agent/system bookkeeping
    # the user doesn't want in the tree. Anything starting with a dot
    # at the top level is filtered for the same reason hidden files
    # have always been.
    project = _create_project(app_client)
    proj_dir = _project_dir(tmp_path, project)

    hidden = proj_dir / ".paraview_snapshots"
    hidden.mkdir()
    (hidden / "snap.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    tree = app_client.get(f"/api/projects/{project['id']}/files").json()
    assert ".paraview_snapshots" not in tree


def test_nested_files_under_agent_folder_carry_full_relative_path(
    app_client, tmp_path
):
    # The frontend's sidebar splits paths by `/` and uses the first
    # segment to key the subfolder, so deeply nested agent files must
    # surface with their full relative path intact (matching the
    # behaviour for blessed folders).
    project = _create_project(app_client)
    proj_dir = _project_dir(tmp_path, project)

    scratch = proj_dir / "Scratch" / "iteration_01"
    scratch.mkdir(parents=True)
    (scratch / "metrics.txt").write_text("residual: 1e-5\n")

    tree = app_client.get(f"/api/projects/{project['id']}/files").json()
    paths = [entry["path"] for entry in tree.get("Scratch", [])]
    assert "Scratch/iteration_01/metrics.txt" in paths
