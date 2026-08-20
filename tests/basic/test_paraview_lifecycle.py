"""Smoke test for the ParaView subprocess lifecycle manager.

Mocks `subprocess.Popen` and the bridge `/ping` probe so the lifecycle
state machine can be exercised without launching real ParaView. We
verify:

- First launch() succeeds and stores a record.
- A second launch() while the first is alive raises
  ParaviewAlreadyRunningError carrying the prior project's name.
- Once the held Popen reports an exit code (user closed ParaView),
  the next launch() succeeds again — the stale record is cleared.
- ParaviewLaunchError fires (and the stale subprocess is torn down)
  when /ping never comes up.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.paraview import lifecycle


class _FakePopen:
    """Minimal stand-in for subprocess.Popen.

    `poll()` returns None while `alive` is True (i.e. the process is
    running), and an exit code once `alive` is flipped off. `terminate`
    / `kill` / `wait` are recorded so the launch-error teardown path
    can be asserted.
    """

    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid
        self.alive = True
        self.terminated = False
        self.killed = False
        self.waited = False

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.terminated = True
        self.alive = False

    def kill(self):
        self.killed = True
        self.alive = False

    def wait(self, timeout=None):
        self.waited = True
        return 0


@pytest.fixture(autouse=True)
def _reset_lifecycle():
    """Each test starts with no live record."""
    lifecycle._reset_for_tests()
    yield
    lifecycle._reset_for_tests()


@pytest.fixture
def project_dir(tmp_path) -> Path:
    d = tmp_path / "case-folder"
    d.mkdir()
    return d


def _patch_popen(monkeypatch, popen: _FakePopen, captured: dict | None = None):
    """Replace subprocess.Popen so launch() never spawns a real process.

    If `captured` is given, it gets populated with `cmd`, `env`, and
    `kwargs` so a test can assert what lifecycle passed through.
    """

    def _fake_popen(cmd, **kwargs):
        if captured is not None:
            captured["cmd"] = cmd
            captured["env"] = kwargs.get("env")
            captured["kwargs"] = kwargs
        return popen

    monkeypatch.setattr(lifecycle.subprocess, "Popen", _fake_popen)


def _patch_ping(monkeypatch, ready: bool):
    """Stub `_ping_bridge` for tests that don't care about orphan recovery.

    `launch()` calls `_ping_bridge` twice now: once at entry (orphan
    detection — True would trigger SIGKILL), then again for readiness
    after the new spawn. Existing tests want the readiness behaviour,
    not the orphan path, so the first call always returns False (no
    orphan) and every subsequent call returns `ready`. Tests that want
    to exercise the orphan branch substitute their own state-based
    `_ping_bridge` mock instead of using this helper.
    """
    state = {"first": True}

    def _ping(port, timeout=1.0):
        if state["first"]:
            state["first"] = False
            return False
        return ready

    monkeypatch.setattr(lifecycle, "_ping_bridge", _ping)


@pytest.mark.asyncio
async def test_launch_succeeds_when_no_instance_held(monkeypatch, project_dir):
    fake = _FakePopen()
    _patch_popen(monkeypatch, fake)
    _patch_ping(monkeypatch, ready=True)

    rec = await lifecycle.launch(
        project_dir=project_dir,
        project_id="proj-1",
        project_name="Cylinder Flow",
    )
    assert rec["pid"] == fake.pid
    assert rec["project_id"] == "proj-1"
    assert rec["project_name"] == "Cylinder Flow"
    assert rec["foam_file"] is None
    assert lifecycle.is_running()


@pytest.mark.asyncio
async def test_second_launch_raises_already_running(monkeypatch, project_dir):
    fake = _FakePopen()
    _patch_popen(monkeypatch, fake)
    _patch_ping(monkeypatch, ready=True)

    await lifecycle.launch(
        project_dir=project_dir,
        project_id="proj-1",
        project_name="Cylinder Flow",
    )

    with pytest.raises(lifecycle.ParaviewAlreadyRunningError) as excinfo:
        await lifecycle.launch(
            project_dir=project_dir,
            project_id="proj-2",
            project_name="Backstep",
        )
    # Error must name the *currently-running* project, not the caller.
    assert excinfo.value.project_name == "Cylinder Flow"


@pytest.mark.asyncio
async def test_launch_succeeds_again_after_user_closes_window(monkeypatch, project_dir):
    fake = _FakePopen()
    _patch_popen(monkeypatch, fake)
    _patch_ping(monkeypatch, ready=True)

    await lifecycle.launch(
        project_dir=project_dir,
        project_id="proj-1",
        project_name="Cylinder Flow",
    )

    # User closes ParaView — `poll()` now returns an exit code.
    fake.alive = False
    assert not lifecycle.is_running()

    fake_2 = _FakePopen(pid=9999)
    _patch_popen(monkeypatch, fake_2)
    _patch_ping(monkeypatch, ready=True)

    rec = await lifecycle.launch(
        project_dir=project_dir,
        project_id="proj-2",
        project_name="Backstep",
    )
    assert rec["pid"] == 9999
    assert rec["project_name"] == "Backstep"


@pytest.mark.asyncio
async def test_launch_sets_pv_project_root_to_project_dir(monkeypatch, project_dir):
    """The bridge resolves relative paths against `PV_PROJECT_ROOT`.

    Without this env var the bridge falls back to its own directory
    (or `os.getcwd()` after our adaptation), and any
    `save_screenshot("Reports/x.png")` from the agent would land
    outside the project. Lifecycle must always set it so the bridge
    sees the active project as its base.
    """
    fake = _FakePopen()
    captured: dict = {}
    _patch_popen(monkeypatch, fake, captured)
    _patch_ping(monkeypatch, ready=True)

    await lifecycle.launch(
        project_dir=project_dir,
        project_id="proj-1",
        project_name="Cylinder Flow",
    )
    env = captured["env"]
    assert env["PV_PROJECT_ROOT"] == str(project_dir)
    # PV_CASE_PATH must NOT be set when foam_file is None — otherwise
    # the bridge tries to auto-load a stale path from the previous run.
    assert "PV_CASE_PATH" not in env


@pytest.mark.asyncio
async def test_launch_passes_foam_file_as_case_path(monkeypatch, project_dir, tmp_path):
    """`PV_CASE_PATH` is how the bridge's auto-loader picks up the case."""
    fake = _FakePopen()
    captured: dict = {}
    _patch_popen(monkeypatch, fake, captured)
    _patch_ping(monkeypatch, ready=True)

    foam = tmp_path / "case.foam"
    foam.touch()
    await lifecycle.launch(
        project_dir=project_dir,
        project_id="proj-1",
        project_name="Cylinder Flow",
        foam_file=str(foam),
    )
    env = captured["env"]
    assert env["PV_CASE_PATH"] == str(foam)
    assert env["PV_PROJECT_ROOT"] == str(project_dir)


@pytest.mark.asyncio
async def test_launch_starts_new_session_for_group_kill(monkeypatch, project_dir):
    """`start_new_session=True` is what makes `force_kill` work.

    The `paraview` binary on this install is a wrapper that execs
    `paraview-real`. Without `start_new_session=True`, `popen.kill()`
    (or `os.killpg(popen.pid, ...)`) only signals the wrapper after
    exec, leaking `paraview-real`. Encode the invariant here so a
    well-meaning refactor can't silently drop the flag.
    """
    fake = _FakePopen()
    captured: dict = {}
    _patch_popen(monkeypatch, fake, captured)
    _patch_ping(monkeypatch, ready=True)

    await lifecycle.launch(
        project_dir=project_dir,
        project_id="proj-1",
        project_name="Cylinder Flow",
    )
    assert captured["kwargs"].get("start_new_session") is True


# ── Orphan recovery ──────────────────────────────────────────────────
#
# When the previous backend died without killing its ParaView, the
# bridge process keeps running and owns port 8765 — but the new
# backend has no `_record` for it. `launch()` probes the port on
# entry, and if /ping responds while `_record` is empty, the listener
# is an orphan from a previous session and we SIGKILL it (process
# group, since ParaView was originally spawned with
# `start_new_session=True`) before spawning fresh. The launch result
# carries `cleaned_orphan: True` so the frontend can toast.


def test_find_pid_on_port_returns_none_when_lsof_missing(monkeypatch):
    """If `lsof` isn't on PATH, return None — let the caller proceed."""
    def _no_lsof(cmd, **kwargs):
        raise FileNotFoundError("lsof")

    monkeypatch.setattr(lifecycle.subprocess, "check_output", _no_lsof)
    assert lifecycle._find_pid_on_port(8765) is None


def test_find_pid_on_port_returns_none_when_nothing_listening(monkeypatch):
    """lsof exits non-zero when no socket matches — None, not an error."""
    import subprocess as _sp

    def _no_match(cmd, **kwargs):
        raise _sp.CalledProcessError(returncode=1, cmd=cmd)

    monkeypatch.setattr(lifecycle.subprocess, "check_output", _no_match)
    assert lifecycle._find_pid_on_port(8765) is None


def test_find_pid_on_port_parses_first_pid_from_lsof_output(monkeypatch):
    """Multi-line lsof output (rare but possible) — take the first PID."""
    monkeypatch.setattr(
        lifecycle.subprocess,
        "check_output",
        lambda cmd, **kwargs: b"3376\n3375\n",
    )
    assert lifecycle._find_pid_on_port(8765) == 3376


def test_kill_orphan_bridge_sigkills_process_group(monkeypatch):
    """The kill targets the orphan's process group, not the bare PID.

    The original ParaView was spawned with `start_new_session=True`,
    so the wrapper is its own process-group leader and `paraview-real`
    (which actually holds the listening socket) is in the same group.
    Group-kill catches both.
    """
    monkeypatch.setattr(lifecycle, "_find_pid_on_port", lambda port: 3376)
    # Simulate the orphan being its own group leader (PGID == PID for
    # the wrapper that spawned start_new_session=True).
    monkeypatch.setattr(lifecycle.os, "getpgid", lambda pid: 3375)

    killpg_calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        lifecycle.os, "killpg",
        lambda pgid, sig: killpg_calls.append((pgid, sig)),
    )
    # Post-kill /ping returns False so the wait loop exits promptly.
    monkeypatch.setattr(
        lifecycle, "_ping_bridge", lambda port, timeout=0.3: False,
    )

    ok = lifecycle._kill_orphan_bridge(8765)
    assert ok is True
    assert killpg_calls == [(3375, lifecycle.signal.SIGKILL)]


def test_kill_orphan_bridge_returns_false_when_pid_not_found(monkeypatch):
    """Nothing to kill — caller proceeds, the bind will fail loudly if
    something else is still in the way."""
    monkeypatch.setattr(lifecycle, "_find_pid_on_port", lambda port: None)
    assert lifecycle._kill_orphan_bridge(8765) is False


@pytest.mark.asyncio
async def test_launch_detects_orphan_kills_it_and_reports_cleanup(
    monkeypatch, project_dir,
):
    """End-to-end orphan recovery in `launch()`.

    Simulates the failure mode: backend was restarted, ParaView from
    the previous session is still listening on 8765. The new launch
    must:
    - notice via /ping that the port is taken,
    - SIGKILL the orphan's process group,
    - spawn fresh,
    - return `cleaned_orphan: True` in the response so the frontend
      can toast.
    """
    # Bridge-alive state, flipped by killpg / new-spawn so /ping
    # returns the right thing at each stage of the flow.
    state = {"bridge_alive": True}

    def _ping(port, timeout=1.0):
        return state["bridge_alive"]

    def _find_pid(port):
        return 3376

    killpg_calls: list[tuple[int, int]] = []

    def _killpg(pgid, sig):
        killpg_calls.append((pgid, sig))
        # Orphan dies — bridge stops responding until the new spawn
        # brings it back.
        state["bridge_alive"] = False

    def _getpgid(pid):
        return 3375  # pretend the orphan's group leader

    fake_popen = _FakePopen(pid=11111)

    def _spawn(cmd, **kwargs):
        # The new ParaView is up — flip the bridge back on so the
        # readiness check (_await_ready → _ping_bridge) passes.
        state["bridge_alive"] = True
        return fake_popen

    monkeypatch.setattr(lifecycle, "_ping_bridge", _ping)
    monkeypatch.setattr(lifecycle, "_find_pid_on_port", _find_pid)
    monkeypatch.setattr(lifecycle.os, "killpg", _killpg)
    monkeypatch.setattr(lifecycle.os, "getpgid", _getpgid)
    monkeypatch.setattr(lifecycle.subprocess, "Popen", _spawn)

    rec = await lifecycle.launch(
        project_dir=project_dir,
        project_id="proj-airfoil",
        project_name="Airfoil",
    )

    # Cleanup actually happened — group-killed at the right PGID with
    # SIGKILL.
    assert killpg_calls, "_kill_orphan_bridge did not call killpg"
    pgid, sig = killpg_calls[0]
    assert pgid == 3375
    assert sig == lifecycle.signal.SIGKILL

    # Response carries the cleanup notice for the frontend toast.
    assert rec.get("cleaned_orphan") is True
    assert rec["project_name"] == "Airfoil"
    assert rec["pid"] == 11111
    assert lifecycle.is_running()


@pytest.mark.asyncio
async def test_launch_does_not_set_cleaned_orphan_when_port_is_free(
    monkeypatch, project_dir,
):
    """Normal launch path — no orphan, no cleanup, no notice."""
    fake = _FakePopen()
    _patch_popen(monkeypatch, fake)

    # First /ping (orphan detection) returns False; subsequent (readiness)
    # return True. iter+next pattern keeps the mock honest about call
    # ordering — if the readiness check fires before the detection, the
    # test breaks loudly instead of accidentally passing.
    pings = iter([False, True, True, True])
    monkeypatch.setattr(
        lifecycle, "_ping_bridge",
        lambda port, timeout=1.0: next(pings, True),
    )

    killpg_calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        lifecycle.os, "killpg",
        lambda pgid, sig: killpg_calls.append((pgid, sig)),
    )

    rec = await lifecycle.launch(
        project_dir=project_dir,
        project_id="proj-cylinder",
        project_name="Cylinder",
    )

    # No orphan handling triggered, no cleanup notice emitted.
    assert "cleaned_orphan" not in rec
    assert killpg_calls == []


@pytest.mark.asyncio
async def test_launch_error_when_bridge_never_responds(monkeypatch, project_dir):
    """If /ping never succeeds, lifecycle tears down the half-spawned
    subprocess so the slot is free for the next attempt.

    The teardown must use a group-kill (`os.killpg`), not just
    `popen.terminate()`, because the `paraview` binary is a shell
    wrapper that execs `paraview-real`. We assert SIGKILL hit the
    group rather than checking a Popen-side flag.
    """
    fake = _FakePopen()
    _patch_popen(monkeypatch, fake)
    _patch_ping(monkeypatch, ready=False)

    killpg_calls: list[tuple[int, int]] = []

    def _fake_killpg(pgid, sig):
        killpg_calls.append((pgid, sig))

    monkeypatch.setattr(lifecycle.os, "killpg", _fake_killpg)

    # Shrink the readiness window so the test is fast (~0.1s).
    monkeypatch.setattr(lifecycle, "_READINESS_TIMEOUT_S", 0.1)
    monkeypatch.setattr(lifecycle, "_READINESS_POLL_INTERVAL_S", 0.05)

    with pytest.raises(lifecycle.ParaviewLaunchError):
        await lifecycle.launch(
            project_dir=project_dir,
            project_id="proj-1",
            project_name="Cylinder Flow",
        )
    assert killpg_calls, "force_kill did not send SIGKILL to the process group"
    pgid, sig = killpg_calls[0]
    assert pgid == fake.pid
    assert sig == lifecycle.signal.SIGKILL
    assert not lifecycle.is_running()
