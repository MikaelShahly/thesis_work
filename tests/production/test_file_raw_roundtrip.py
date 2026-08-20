"""GET /api/projects/{id}/file/raw — serve figure bytes end-to-end.

Exercises the real path: create a project (DB + folders), drop a figure
on disk, and fetch it back through the endpoint the frontend's <img>
points at. Confirms the bytes survive intact, the content-type is
right (including the pinned image/svg+xml), and the ../ containment
guard holds.
"""

from __future__ import annotations

import importlib
import sys

import pytest
from fastapi.testclient import TestClient

PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 16
SVG_TEXT = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'


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
    res = client.post("/api/projects", json={"name": "figure-test"})
    assert res.status_code == 200, res.text
    return res.json()


def _project_dir(tmp_path, project):
    return tmp_path / "projects" / project["folder_name"]


def test_png_bytes_round_trip_intact(app_client, tmp_path):
    project = _create_project(app_client)
    (_project_dir(tmp_path, project) / "Reports" / "plot.png").write_bytes(PNG_BYTES)

    res = app_client.get(
        f"/api/projects/{project['id']}/file/raw", params={"path": "Reports/plot.png"}
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "image/png"
    assert res.content == PNG_BYTES


def test_svg_served_as_image_svg_xml(app_client, tmp_path):
    project = _create_project(app_client)
    (_project_dir(tmp_path, project) / "Reports" / "fig.svg").write_text(SVG_TEXT)

    res = app_client.get(
        f"/api/projects/{project['id']}/file/raw", params={"path": "Reports/fig.svg"}
    )
    assert res.status_code == 200, res.text
    # Pinned regardless of the host's mimetypes table, so the browser
    # renders the image rather than showing raw XML.
    assert res.headers["content-type"] == "image/svg+xml"
    assert res.text == SVG_TEXT


def test_html_report_served_inline_as_text_html(app_client, tmp_path):
    # post_process HTML deliverable: the frontend embeds it in an
    # <iframe>, so it must be served inline (not as an attachment) with
    # a text/html content-type for the browser to render it.
    project = _create_project(app_client)
    html = "<!doctype html><html><body><h1>Report</h1></body></html>"
    (_project_dir(tmp_path, project) / "Reports" / "report.html").write_text(html)

    res = app_client.get(
        f"/api/projects/{project['id']}/file/raw",
        params={"path": "Reports/report.html"},
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/html")
    # No attachment disposition — must render inline in the iframe.
    assert "attachment" not in res.headers.get("content-disposition", "")
    assert res.text == html


def test_pdf_report_served_as_application_pdf(app_client, tmp_path):
    # post_process PDF deliverable: rendered inline by the browser's
    # native PDF viewer in the iframe / new tab.
    project = _create_project(app_client)
    pdf_bytes = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n"
    (_project_dir(tmp_path, project) / "Reports" / "report.pdf").write_bytes(pdf_bytes)

    res = app_client.get(
        f"/api/projects/{project['id']}/file/raw",
        params={"path": "Reports/report.pdf"},
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert "attachment" not in res.headers.get("content-disposition", "")
    assert res.content == pdf_bytes


def test_path_traversal_is_rejected(app_client):
    project = _create_project(app_client)
    res = app_client.get(
        f"/api/projects/{project['id']}/file/raw",
        params={"path": "../../etc/passwd"},
    )
    assert res.status_code == 400


def test_missing_file_is_404(app_client):
    project = _create_project(app_client)
    res = app_client.get(
        f"/api/projects/{project['id']}/file/raw",
        params={"path": "Reports/nope.png"},
    )
    assert res.status_code == 404
