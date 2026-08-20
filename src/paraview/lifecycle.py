"""Backend-side ParaView lifecycle.

Owns one slot: the single ParaView subprocess (the bridge is global,
not per-project). `launch()` spawns ParaView with our bridge script
and waits until the bridge HTTP server replies on `/ping`. A second
`launch()` while the first instance is still alive raises
`ParaviewAlreadyRunningError` so the caller can return a 409 with the
project name of the active session.

Orphan recovery: if the previous backend died without killing its
ParaView, the bridge process keeps running and holds port 8765 — but
the new backend has no record of it. `launch()` probes the bridge
port on entry; if /ping responds while `_record` is empty, the
process is an orphan from a previous session and we SIGKILL it
before spawning the new ParaView. The launch result includes
`cleaned_orphan: True` so the frontend can surface a toast telling
the user what happened.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


# Single project-wide bridge port. Mirrored in
# `src/tools/paraview/_client.py` (both honour `PV_BRIDGE_PORT` for
# tests).
DEFAULT_BRIDGE_PORT = 8765

# Time we will wait for the bridge HTTP server to come up after we
# spawn ParaView. ParaView's Qt GUI takes a couple of seconds; on
# WSLg / cold caches it can take longer.
_READINESS_TIMEOUT_S = 30.0
_READINESS_POLL_INTERVAL_S = 0.25

# Path to the bridge script we hand to `paraview --script=…`.
# Resolved by sibling, NOT by importing the module — bridge.py pulls in
# `vtkmodules` and runs ParaView side-effects at import time, neither
# of which exists in the backend interpreter.
_BRIDGE_SCRIPT_PATH = (Path(__file__).parent / "bridge.py").resolve()


class ParaviewAlreadyRunningError(RuntimeError):
    """Raised when launch() is called while an instance is alive.

    Carries the project name of the running session so the route can
    surface it in the 409 detail. Lifecycle never silently kills the
    existing process — closing it is the user's gesture.
    """

    def __init__(self, project_name: str) -> None:
        super().__init__(
            f"ParaView is already open for {project_name!r}. "
            "Close that window and try again."
        )
        self.project_name = project_name


class ParaviewLaunchError(RuntimeError):
    """Raised when ParaView spawned but the bridge never came up."""


@dataclass
class _LiveRecord:
    popen: subprocess.Popen
    pid: int
    project_id: str
    project_name: str
    foam_file: str | None
    port: int
    log_file: object = None  # open file handle for ParaView's stdout/stderr

    def is_alive(self) -> bool:
        return self.popen.poll() is None

    def force_kill(self, timeout: float = 5.0) -> None:
        """SIGKILL the whole process group, not just the wrapper.

        The `paraview` binary on most installs is a shell wrapper that
        execs `paraview-real`. Calling `popen.kill()` only signals the
        wrapper; if it has already exec'd, the real ParaView keeps
        running. We start Popen with `start_new_session=True` so the
        child is the leader of its own process group; sending SIGKILL
        to the group catches the wrapper, `paraview-real`, and any
        helper it spawned.
        """
        try:
            os.killpg(self.popen.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            self.popen.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass
        if self.log_file is not None:
            try:
                self.log_file.close()
            except Exception:
                pass


_record: _LiveRecord | None = None
_lock = asyncio.Lock()


def _bridge_port() -> int:
    return int(os.environ.get("PV_BRIDGE_PORT", str(DEFAULT_BRIDGE_PORT)))


def _paraview_executable() -> str:
    # Allow override for unusual installs (WSL2, custom prefixes).
    # The default `paraview` is what the test project uses; if it's
    # not on PATH the launch will fail with a clear FileNotFoundError.
    return os.environ.get("PARAVIEW_EXECUTABLE", "paraview")


def _paraview_log_path(port: int) -> Path:
    """Transient logfile for ParaView's stdout/stderr (system temp)."""
    return Path(tempfile.gettempdir()) / f"agenticcfd_paraview_{port}.log"


# C-level / VTK crash signatures that have no faulthandler header but still
# mean ParaView died (vs. a clean user-initiated window close).
_CRASH_SIGNATURES = (
    "Segmentation fault",
    "free(): invalid pointer",
    "munmap_chunk",
    "double free",
    "Aborted",
    "core dumped",
    "terminate called",
)


def read_paraview_log_tail(max_chars: int = 2500) -> str | None:
    """Return ParaView's crash output, or None if it did not crash.

    Only returns something when the log actually contains a crash: the
    faulthandler dump ("Fatal Python error", returned from that point minus
    the multi-kilobyte "Extension modules:" line, which is pure noise), or a
    C-level abort signature. A normally-closed ParaView leaves only startup
    chatter in the log, which must NOT be surfaced — otherwise a plain
    "bridge unreachable" would get irrelevant noise attached. Used by the
    HTTP client to enrich a RemoteDisconnected with the real cause.
    """
    rec = _record
    if rec is None or rec.log_file is None:
        return None
    try:
        text = Path(rec.log_file.name).read_text(errors="replace")
    except OSError:
        return None
    if not text.strip():
        return None
    marker = text.find("Fatal Python error")
    if marker != -1:
        text = text[marker:]
        ext = text.find("\nExtension modules:")
        if ext != -1:
            text = text[:ext]
        return text.strip()
    if any(sig in text for sig in _CRASH_SIGNATURES):
        return text[-max_chars:].strip()
    return None


def _ping_bridge(port: int, timeout: float = 1.0) -> bool:
    url = f"http://127.0.0.1:{port}/ping"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            json.loads(resp.read().decode("utf-8") or "{}")
            return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def _await_ready(port: int, deadline: float) -> None:
    """Block until /ping responds or the deadline is reached."""
    while time.monotonic() < deadline:
        if _ping_bridge(port):
            return
        time.sleep(_READINESS_POLL_INTERVAL_S)
    raise ParaviewLaunchError(
        f"ParaView bridge did not respond on port {port} within "
        f"{_READINESS_TIMEOUT_S:.0f}s. Check ParaView started and "
        "the bridge script loaded without errors."
    )


def _find_pid_on_port(port: int) -> int | None:
    """Return the PID of the process listening on `port`, or None.

    Uses `lsof -ti :<port> -sTCP:LISTEN`. Returns None if `lsof` is
    not on PATH, nothing is listening, or the lookup otherwise fails
    — callers must tolerate the None case (orphan kill becomes a
    no-op, the new bind will surface the underlying error).
    """
    try:
        out = subprocess.check_output(
            ["lsof", "-ti", f":{port}", "-sTCP:LISTEN"],
            stderr=subprocess.DEVNULL,
            timeout=2.0,
        )
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        return None
    text = out.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        # lsof can return multiple PIDs (one per line) if several
        # sockets bind the same address; take the first — they'll all
        # belong to the same process group in our case anyway.
        return int(text.splitlines()[0])
    except (ValueError, IndexError):
        return None


def _kill_orphan_bridge(port: int) -> bool:
    """SIGKILL the (presumed-orphan) bridge listening on `port`.

    Returns True if a process was found and the listener cleared,
    False if we couldn't identify or kill it.

    The caller is expected to have already confirmed the listener is
    *our* bridge (via `_ping_bridge`) — this function does not
    re-check. We SIGKILL the process group rather than the bare PID
    because the original backend spawned ParaView with
    `start_new_session=True`, making the wrapper a process-group
    leader; group-kill catches both the wrapper and `paraview-real`
    (which is what actually holds the listening socket).
    """
    pid = _find_pid_on_port(port)
    if pid is None:
        return False

    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        # Process died between lookup and kill, or owned by a different
        # user. Best-effort: try a plain SIGKILL on the PID.
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            return False

    # Wait briefly for the kernel to release the listening socket.
    # Probe via /ping (rather than re-running lsof) so we don't
    # depend on lsof being present for the wait loop. Cap at ~3s —
    # SIGKILL releases the socket essentially immediately, so a long
    # wait here would be a symptom of something else going wrong.
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if not _ping_bridge(port, timeout=0.3):
            return True
        time.sleep(0.1)
    # Bridge is still answering after 3s of SIGKILL waiting — something
    # is wrong. Surface True anyway so the caller proceeds with the new
    # spawn; the new bind will fail loudly if the port is still busy.
    return True


def is_running() -> bool:
    """Cheap liveness check: held record + Popen still alive."""
    return _record is not None and _record.is_alive()


def is_bridge_up() -> bool:
    """True if anything answers the bridge `/ping` on the bridge port.

    Wider than `is_running()`: catches an orphan bridge from a previous
    backend that has no in-memory record. Used by the `launch_paraview`
    agent tool to refuse a second launch whenever *any* instance is
    already up — the agent never kills what it didn't start.
    """
    return _ping_bridge(_bridge_port())


def current_project() -> tuple[str, str] | None:
    """Return `(project_id, project_name)` of the live session, or None."""
    if not is_running():
        return None
    assert _record is not None
    return _record.project_id, _record.project_name


def _serialize(rec: _LiveRecord) -> dict:
    return {
        "pid": rec.pid,
        "project_id": rec.project_id,
        "project_name": rec.project_name,
        "foam_file": rec.foam_file,
        "port": rec.port,
    }


async def launch(
    *,
    project_dir: Path,
    project_id: str,
    project_name: str,
    foam_file: str | None = None,
) -> dict:
    """Spawn ParaView with our bridge attached. See module docstring."""
    global _record

    cleaned_orphan = False

    async with _lock:
        # Step 1+2: reject if already alive; clear stale record.
        if _record is not None:
            if _record.is_alive():
                raise ParaviewAlreadyRunningError(_record.project_name)
            _record = None

        port = _bridge_port()

        # Orphan recovery: we have no record, but is the bridge port
        # already taken? That happens when the previous backend died
        # without killing ParaView, leaving the bridge listening
        # untracked. We /ping first to confirm what's there is our
        # bridge (so we don't accidentally kill some unrelated server
        # bound to the same port), then SIGKILL the orphan's process
        # group before spawning the new instance. The frontend toasts
        # off `cleaned_orphan: True` so the user knows what happened.
        if _ping_bridge(port):
            cleaned_orphan = await asyncio.to_thread(
                _kill_orphan_bridge, port,
            )

        env = {
            **os.environ,
            "PV_BRIDGE_PORT": str(port),
            # Anchor the bridge's relative-path resolution to the
            # active project, so `save_screenshot("Cases/baseline/x.png")`,
            # `load_dataset("Geometry/cylinder.stl")`, and the
            # auto-snapshot directory all land inside the project tree
            # rather than next to bridge.py in src/paraview/.
            "PV_PROJECT_ROOT": str(project_dir),
            # Dump a Python traceback to stderr on a fatal signal
            # (SIGSEGV etc.). A bare ParaView segfault prints nothing, so
            # without this a crash is invisible; with it we capture which
            # bridge call died. Read back by read_paraview_log_tail() and
            # surfaced to the agent instead of an opaque RemoteDisconnected.
            "PYTHONFAULTHANDLER": "1",
        }
        if foam_file is not None:
            # bridge.py auto-loads PV_CASE_PATH if set.
            env["PV_CASE_PATH"] = str(foam_file)

        cmd = [
            _paraview_executable(),
            f"--script={_BRIDGE_SCRIPT_PATH}",
        ]

        # Capture ParaView's stdout+stderr to a transient logfile so a
        # crash is readable. Kept in the system temp dir (not the project
        # tree — it is debug scratch, not a project artifact) and
        # truncated each launch. A real file never blocks the child, so
        # this is behaviourally inert.
        log_path = _paraview_log_path(port)
        log_file = open(log_path, "wb")

        try:
            popen = subprocess.Popen(
                cmd,
                env=env,
                cwd=str(project_dir),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                # New session/process group so a later SIGKILL to the
                # group catches `paraview-real` (the wrapper execs it)
                # and any helpers, not just the shell wrapper.
                start_new_session=True,
            )
        except FileNotFoundError as e:
            log_file.close()
            raise ParaviewLaunchError(
                f"Could not start ParaView: {e}. Set PARAVIEW_EXECUTABLE "
                "if the binary is not on PATH."
            ) from e

        provisional = _LiveRecord(
            popen=popen,
            pid=popen.pid,
            project_id=project_id,
            project_name=project_name,
            foam_file=foam_file,
            port=port,
            log_file=log_file,
        )

        # Step 3: poll /ping until ready, off the event loop so we
        # don't block other backend work.
        deadline = time.monotonic() + _READINESS_TIMEOUT_S
        try:
            await asyncio.to_thread(_await_ready, port, deadline)
        except ParaviewLaunchError:
            # Tear down the half-started subprocess so the slot is
            # free. Group-kill, not popen.kill(), or the real ParaView
            # behind the wrapper script survives.
            provisional.force_kill()
            raise

        _record = provisional
        result = _serialize(_record)
        if cleaned_orphan:
            # Surfaces in the /paraview/launch response so the
            # frontend can render a "untracked instance was running,
            # starting a new one" toast.
            result["cleaned_orphan"] = True
        return result


def _reset_for_tests() -> None:
    """Clear in-memory state. Test helper only — never call from app code."""
    global _record
    _record = None
