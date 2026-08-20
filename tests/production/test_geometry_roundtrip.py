"""Geometry upload round-trip — API in, on-disk out, agent-readable.

The goal of this production test is to prove the assumption phase 5
relies on: a user upload via `POST /geometry` lands at
`<project>/Geometry/<file>`, and an agent whose cwd is anywhere
inside the project (every phase now runs from the project root, and
cases live under `Cases/<name>/`) can `Read` the file by a
project-relative path.

We don't spin up the full Claude SDK — the `Read` tool is a
built-in CLI tool we don't own, and what matters is the on-disk
contract it depends on. We assert:
  - the file is at the exact path the agent's prompt will reference;
  - byte-for-byte the upload survives the round-trip (no transcoding,
    no truncation, no rename surprises);
  - file is readable from a sibling subfolder via `../Geometry/<file>`,
    matching what `Read("../Geometry/cylinder.stl")` would resolve.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


_ASCII_STL = b"""solid roundtrip
  facet normal 0 0 1
    outer loop
      vertex 0 0 0
      vertex 1 0 0
      vertex 0 1 0
    endloop
  endfacet
endsolid roundtrip
"""


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """Same isolation pattern as the basic test: tmp DB, tmp projects/."""
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


def test_upload_roundtrips_to_disk_and_is_agent_readable(app_client, tmp_path):
    project = app_client.post(
        "/api/projects", json={"name": "Cylinder Flow"}
    ).json()

    res = app_client.post(
        f"/api/projects/{project['id']}/geometry",
        files={"file": ("cylinder.stl", _ASCII_STL, "model/stl")},
    )
    assert res.status_code == 200, res.text
    record = res.json()

    proj_root = tmp_path / "projects" / project["folder_name"]
    abs_path = proj_root / record["path"]

    # 1. Path the agent's prompt would reference.
    assert record["path"] == "Geometry/cylinder.stl"

    # 2. Byte-for-byte identical to what we uploaded.
    assert abs_path.is_file()
    assert abs_path.read_bytes() == _ASCII_STL

    # 3. Reachable from inside a case via the relative path an agent
    #    working under `Cases/<name>/` would use. Cases live two levels
    #    below the project root (e.g. `Cases/baseline/`), so
    #    `Read("../../Geometry/cylinder.stl")` is the natural call.
    case_dir = proj_root / "Cases" / "baseline"
    case_dir.mkdir(parents=True, exist_ok=True)
    relative_from_case = case_dir / ".." / ".." / "Geometry" / "cylinder.stl"
    assert relative_from_case.resolve() == abs_path.resolve()
    assert relative_from_case.read_bytes() == _ASCII_STL

    # 4. Reachable from cwd=<project root> via the relative path the
    #    mesh agent would use (its cwd settles at the project root).
    relative_from_root = proj_root / "Geometry" / "cylinder.stl"
    assert relative_from_root.read_bytes() == _ASCII_STL


def test_collision_renamed_file_is_also_agent_readable(app_client, tmp_path):
    """A second upload of the same name collides → `_1` suffix.

    The renamed file must appear at a fresh project-relative path so
    the agent can disambiguate by name without scanning the directory
    every turn. Failing this would leak collision handling into the
    agent prompt (it would have to know that uploads silently
    overwrite or be sorted by recency).
    """
    project = app_client.post(
        "/api/projects", json={"name": "Cylinder Flow"}
    ).json()

    first = app_client.post(
        f"/api/projects/{project['id']}/geometry",
        files={"file": ("cylinder.stl", _ASCII_STL, "model/stl")},
    ).json()
    second = app_client.post(
        f"/api/projects/{project['id']}/geometry",
        files={"file": ("cylinder.stl", _ASCII_STL + b"second", "model/stl")},
    ).json()

    assert first["path"] == "Geometry/cylinder.stl"
    assert second["path"] == "Geometry/cylinder_1.stl"

    proj_root = tmp_path / "projects" / project["folder_name"]
    assert (proj_root / first["path"]).read_bytes() == _ASCII_STL
    assert (proj_root / second["path"]).read_bytes() == _ASCII_STL + b"second"
