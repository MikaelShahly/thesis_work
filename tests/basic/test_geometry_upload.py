"""POST /api/projects/{id}/geometry — accept, reject, collide.

Drives the FastAPI app through TestClient against a real on-disk
project (DB + folders) materialised inside `tmp_path`. The upload
endpoint is the only surface here; we don't go near the SDK or any
agent loop.

Coverage targets from phase-3 §3.4:
- Endpoint accepts a small STL, writes it to the right folder, and
  the file shows up in `GET /files` under `Geometry/`.
- Rejection of a `.exe` upload returns 415 with the allow-list in
  the error detail.
- Filename collision: a second upload of `cylinder.stl` becomes
  `cylinder_1.stl`.

Plus a couple of defensive checks (path-traversal, leading-dot
stripping) since those live in the same sanitiser.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """Spin up the FastAPI app against a tmp DB + tmp projects/ root.

    The DB path and PROJECTS_DIR are patched via monkeypatch BEFORE
    the app modules are imported so their module-level constants
    pick up the temp values. Each test gets a fresh DB; project
    folders are created inside `tmp_path` and torn down with it.
    """
    db_path = tmp_path / "agenticcfd.db"
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    # `src.config` is import-time read by both `src.db` and
    # `src.api.routes`; patch before either gets imported.
    import src.config as config

    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "PROJECTS_DIR", projects_dir)

    # Force a fresh import of the modules that captured the constants
    # at module load. Using importlib.reload would also work; we go
    # via sys.modules so the lifespan-driven init_db() picks up the
    # patched DB_PATH.
    import importlib
    import sys

    for mod in ("src.db", "src.api.routes", "src.api.app"):
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])

    from src.api.app import app

    with TestClient(app) as client:
        yield client


def _create_project(client: TestClient, name: str = "Cylinder Flow") -> dict:
    res = client.post("/api/projects", json={"name": name})
    assert res.status_code == 200, res.text
    return res.json()


_ASCII_STL = b"""solid cube
  facet normal 0 0 1
    outer loop
      vertex 0 0 0
      vertex 1 0 0
      vertex 0 1 0
    endloop
  endfacet
endsolid cube
"""


def test_uploaded_stl_lands_in_geometry_folder(app_client: TestClient, tmp_path):
    project = _create_project(app_client)

    res = app_client.post(
        f"/api/projects/{project['id']}/geometry",
        files={"file": ("cylinder.stl", _ASCII_STL, "model/stl")},
    )
    assert res.status_code == 200, res.text
    record = res.json()
    assert record["name"] == "cylinder.stl"
    assert record["path"] == "Geometry/cylinder.stl"
    assert record["type"] == "stl"
    assert record["subfolder"] == "Geometry"
    assert record["size"] == len(_ASCII_STL)

    # File present on disk under the project's Geometry folder.
    on_disk = tmp_path / "projects" / project["folder_name"] / "Geometry" / "cylinder.stl"
    assert on_disk.is_file()
    assert on_disk.read_bytes() == _ASCII_STL

    # And surfaced through the file-tree endpoint the sidebar reads.
    tree = app_client.get(f"/api/projects/{project['id']}/files").json()
    geometry_paths = [entry["path"] for entry in tree["Geometry"]]
    assert "Geometry/cylinder.stl" in geometry_paths


def test_disallowed_extension_returns_415(app_client: TestClient):
    project = _create_project(app_client)
    res = app_client.post(
        f"/api/projects/{project['id']}/geometry",
        files={"file": ("payload.exe", b"MZ\x90\x00", "application/octet-stream")},
    )
    assert res.status_code == 415, res.text
    detail = res.json()["detail"]
    # The error names the offending extension AND lists the allow-set
    # so the user can pick a valid one.
    assert ".exe" in detail
    assert ".stl" in detail


def test_filename_collision_appends_numeric_suffix(app_client: TestClient, tmp_path):
    project = _create_project(app_client)
    payload = {"file": ("cylinder.stl", _ASCII_STL, "model/stl")}

    first = app_client.post(
        f"/api/projects/{project['id']}/geometry", files=payload
    ).json()
    second = app_client.post(
        f"/api/projects/{project['id']}/geometry",
        files={"file": ("cylinder.stl", _ASCII_STL, "model/stl")},
    ).json()

    assert first["path"] == "Geometry/cylinder.stl"
    assert second["path"] == "Geometry/cylinder_1.stl"

    geom_dir = tmp_path / "projects" / project["folder_name"] / "Geometry"
    assert (geom_dir / "cylinder.stl").is_file()
    assert (geom_dir / "cylinder_1.stl").is_file()


def test_path_traversal_attempt_strips_to_basename(app_client: TestClient, tmp_path):
    project = _create_project(app_client)
    res = app_client.post(
        f"/api/projects/{project['id']}/geometry",
        files={"file": ("../../escape.stl", _ASCII_STL, "model/stl")},
    )
    # The sanitiser keeps only the basename — the upload succeeds at
    # `Geometry/escape.stl`, never escaping the project folder.
    assert res.status_code == 200, res.text
    assert res.json()["path"] == "Geometry/escape.stl"

    proj_root = tmp_path / "projects" / project["folder_name"]
    assert (proj_root / "Geometry" / "escape.stl").is_file()
    # Belt-and-braces: nothing landed *outside* the project root.
    assert not (tmp_path / "escape.stl").exists()
    assert not (tmp_path / "projects" / "escape.stl").exists()


def test_leading_dot_filename_is_stripped(app_client: TestClient):
    # Leading dots would create hidden files inside Geometry/. We
    # strip them so an upload always shows up in the tree.
    project = _create_project(app_client)
    res = app_client.post(
        f"/api/projects/{project['id']}/geometry",
        files={"file": (".hidden.stl", _ASCII_STL, "model/stl")},
    )
    assert res.status_code == 200, res.text
    assert res.json()["path"] == "Geometry/hidden.stl"


def test_get_file_returns_binary_placeholder_for_binary_geometry(
    app_client: TestClient,
):
    """`GET /file` no longer 415s on non-text files.

    Binary geometry uploads (binary STL, .step) used to crash the
    file viewer with a 415 from the read-text probe; phase 3 swaps
    that for a `is_binary: true` payload the FilePanel renders as a
    'Binary geometry file · <size>' placeholder.
    """
    project = _create_project(app_client)
    # Smallest valid binary STL: 80-byte header + 4-byte triangle
    # count. NUL bytes alone *are* valid UTF-8, so we sprinkle a
    # bare 0x80 continuation byte into the header — that's
    # unambiguously not the start of a UTF-8 codepoint and trips
    # the read-text probe in `read_project_file`.
    header = b"\x80" + b"\x00" * 79
    binary_stl = header + (0).to_bytes(4, "little")
    upload = app_client.post(
        f"/api/projects/{project['id']}/geometry",
        files={"file": ("blob.stl", binary_stl, "model/stl")},
    )
    assert upload.status_code == 200, upload.text

    detail = app_client.get(
        f"/api/projects/{project['id']}/file",
        params={"path": "Geometry/blob.stl"},
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["is_binary"] is True
    assert body["content"] is None
    assert body["size"] == len(binary_stl)


def test_get_file_returns_text_for_ascii_stl(app_client: TestClient):
    project = _create_project(app_client)
    app_client.post(
        f"/api/projects/{project['id']}/geometry",
        files={"file": ("ascii.stl", _ASCII_STL, "model/stl")},
    )
    body = app_client.get(
        f"/api/projects/{project['id']}/file",
        params={"path": "Geometry/ascii.stl"},
    ).json()
    assert body["is_binary"] is False
    assert body["content"].startswith("solid cube")
    assert body["size"] == len(_ASCII_STL)
