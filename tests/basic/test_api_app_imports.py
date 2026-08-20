"""Smoke check that the FastAPI app + routes import cleanly.

The new ParaView routes (`/paraview/launch`, `/paraview/load`) pull in
the lifecycle module and the tool client; if any of those imports
fails, the whole app fails to start. This test catches that early —
much faster than running uvicorn just to see an ImportError.
"""

from fastapi.routing import APIRoute


def test_app_imports_and_registers_paraview_routes():
    # Imported here rather than at module top so collection errors
    # surface inside the test body and pytest reports them per-test.
    from src.api.app import app

    paths = {
        route.path
        for route in app.routes
        if isinstance(route, APIRoute)
    }

    assert "/api/projects/{project_id}/paraview/launch" in paths
    assert "/api/projects/{project_id}/paraview/load" in paths


def test_paraview_routes_are_post_only():
    from src.api.app import app

    by_path = {
        route.path: route
        for route in app.routes
        if isinstance(route, APIRoute)
    }

    launch = by_path["/api/projects/{project_id}/paraview/launch"]
    load = by_path["/api/projects/{project_id}/paraview/load"]
    assert launch.methods == {"POST"}
    assert load.methods == {"POST"}
