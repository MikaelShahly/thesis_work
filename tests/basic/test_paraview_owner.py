"""Unit test for ParaView ownership guard logic (no SDK needed)."""

import asyncio

from src.agent import paraview_owner as po


def _run(coro):
    # Fresh loop per call: a prior pytest-asyncio test can leave the
    # thread's event loop unset, which makes get_event_loop() raise.
    return asyncio.run(coro)


def test_guard_allows_when_no_active_project_set():
    po.set_active_project(None)
    guard = po.make_paraview_guard("project-A")
    out = _run(guard({"tool_name": "mcp__paraview__set_camera"}, "id", None))
    assert out == {}  # fail-open when nothing to enforce against


def test_guard_allows_active_project():
    po.set_active_project("project-A")
    guard = po.make_paraview_guard("project-A")
    out = _run(guard({"tool_name": "mcp__paraview__apply_clip_filter"}, "id", None))
    assert out == {}  # active project → allowed


def test_guard_denies_non_active_project():
    po.set_active_project("project-B")
    guard = po.make_paraview_guard("project-A")  # A is not active
    out = _run(guard({"tool_name": "mcp__paraview__set_camera"}, "id", None))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "live ParaView" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_guard_ignores_non_paraview_tools():
    po.set_active_project("project-B")
    guard = po.make_paraview_guard("project-A")
    for tool in ("Bash", "Read", "Write", "mcp__other__thing"):
        out = _run(guard({"tool_name": tool}, "id", None))
        assert out == {}, f"{tool} should not be gated by ParaView guard"


def test_is_paraview_tool():
    assert po.is_paraview_tool("mcp__paraview__paraview_exec")
    assert po.is_paraview_tool("mcp__paraview__save_screenshot")
    assert not po.is_paraview_tool("Bash")
    assert not po.is_paraview_tool("mcp__paraview")  # prefix must be complete


if __name__ == "__main__":
    test_guard_allows_when_no_active_project_set()
    test_guard_allows_active_project()
    test_guard_denies_non_active_project()
    test_guard_ignores_non_paraview_tools()
    test_is_paraview_tool()
    print("PASS — ParaView ownership guard logic correct")
