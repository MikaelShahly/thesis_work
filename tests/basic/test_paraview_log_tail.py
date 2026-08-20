"""Unit tests for the ParaView crash-log tail reader.

`read_paraview_log_tail` is what turns an opaque RemoteDisconnected into an
actionable error for the agent — it extracts the faulthandler traceback from
ParaView's captured stderr. Exercised here without a live ParaView by pointing
the lifecycle record at a hand-written log file.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.paraview import lifecycle


@dataclass
class _FakeHandle:
    name: str


def _set_record(tmp_path, text: str | None):
    if text is None:
        lifecycle._record = None
        return
    log = tmp_path / "pv.log"
    log.write_text(text)
    # read_paraview_log_tail only touches _record.log_file.name.
    lifecycle._record = type("R", (), {"log_file": _FakeHandle(str(log))})()


_FAULT = """\
[bridge] HTTP server on http://127.0.0.1:8765
[bridge] PV_CASE_PATH not set; skipping auto-load
Fatal Python error: Segmentation fault

Current thread 0x0000 (most recent call first):
  File "<pv-exec>", line 9 in <module>
  File "<string>", line 72 in _drain_queue

Extension modules: vtkmodules.vtkCommonCore, paraview.modules.vtkRemotingCore (total: 169)
"""


def test_extracts_fault_and_strips_extension_modules(tmp_path):
    try:
        _set_record(tmp_path, _FAULT)
        tail = lifecycle.read_paraview_log_tail()
    finally:
        lifecycle._reset_for_tests()
    assert tail is not None
    assert tail.startswith("Fatal Python error: Segmentation fault")
    assert "<pv-exec>" in tail and "_drain_queue" in tail
    # The multi-kilobyte module list is noise and must be dropped.
    assert "Extension modules:" not in tail
    # And the pre-crash startup chatter is trimmed off the front.
    assert "[bridge] HTTP server" not in tail


def test_tail_fallback_when_no_fault_marker(tmp_path):
    try:
        _set_record(tmp_path, "some startup\nfree(): invalid pointer\n")
        tail = lifecycle.read_paraview_log_tail()
    finally:
        lifecycle._reset_for_tests()
    assert tail is not None
    assert "free(): invalid pointer" in tail


def test_none_when_only_startup_chatter(tmp_path):
    # Clean window close leaves no crash signature -> nothing to surface.
    try:
        _set_record(
            tmp_path,
            "[bridge] HTTP server on http://127.0.0.1:8765\n"
            "[bridge] PV_CASE_PATH not set; skipping auto-load\n",
        )
        assert lifecycle.read_paraview_log_tail() is None
    finally:
        lifecycle._reset_for_tests()


def test_none_when_no_record(tmp_path):
    try:
        _set_record(tmp_path, None)
        assert lifecycle.read_paraview_log_tail() is None
    finally:
        lifecycle._reset_for_tests()


def test_none_when_log_empty(tmp_path):
    try:
        _set_record(tmp_path, "   \n  ")
        assert lifecycle.read_paraview_log_tail() is None
    finally:
        lifecycle._reset_for_tests()
