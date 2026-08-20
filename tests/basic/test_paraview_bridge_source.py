"""Structural checks on bridge.py.

bridge.py runs inside ParaView's Python interpreter (it imports
`vtkmodules` and `paraview.simple`), so we can't import it from the
backend test process. Instead we read it as text and assert
invariants that, if broken, would silently mis-route the agent's
file writes.

The invariant we care about: every relative-path call site in the
bridge (`load_dataset`, `save_screenshot`, `export_snapshot`, plus
`SNAPSHOT_DIR`) must anchor on `PV_PROJECT_ROOT`. The previous
version used `HERE` (the bridge script's own directory), which made
agent-written screenshots land inside `src/paraview/` rather than
the active project. `export_snapshot` is no longer an MCP tool but
its bridge endpoint persists for the future frontend snapshot route,
so the path-anchor check still applies to it.
"""

from pathlib import Path


_BRIDGE_PATH = Path(__file__).resolve().parents[2] / "src" / "paraview" / "bridge.py"


def _source() -> str:
    return _BRIDGE_PATH.read_text()


def test_bridge_reads_pv_project_root_env_var():
    # The exact assignment shape matters: an `or` fallback to
    # `os.getcwd()` keeps the bridge usable in ad-hoc runs that
    # forget to set the env var.
    src = _source()
    assert 'os.environ.get("PV_PROJECT_ROOT")' in src
    assert "BASE_DIR" in src


def test_bridge_no_longer_uses_HERE_for_path_resolution():
    # Defensive: a casual refactor must not bring `HERE` back. If
    # someone genuinely wants to add a different anchor, they should
    # update this test too — naming it makes the regression visible.
    src = _source()
    assert "HERE" not in src, (
        "bridge.py uses HERE again; relative agent paths will land "
        "next to bridge.py instead of inside the project."
    )


def test_relative_path_helpers_use_base_dir():
    # Three call sites (load_dataset, save_screenshot,
    # export_snapshot) must all anchor on BASE_DIR. Spot-check that
    # the substring appears at least three times.
    src = _source()
    occurrences = src.count("os.path.join(BASE_DIR")
    assert occurrences >= 3, (
        f"expected ≥3 BASE_DIR-anchored path joins, found {occurrences}"
    )
