"""Registry + lifecycle for persistent SessionWorkers.

One worker per (project, phase) session, keyed by DB `session_id`. This
module owns the lifecycle policy:

  * **Never close the active project.** The active project is the one the
    frontend is viewing (`paraview_owner.active_project_id()` — the same
    token used for ParaView ownership).
  * **Close-check** = close a worker iff it is *not* the active project,
    has *no* active turn, and has *no* running background task. Evaluated
    at three event triggers (no poll loop):
        - switch-away  → `on_active_project_changed()`
        - turn end / task completion → the worker's `on_state_change`
          callback (wired here to `_schedule_close_check`).
  * **No cap** — idle sessions reclaim themselves via the close-check;
    busy ones (running task) persist until their task finishes.

Single-process, single FastAPI worker — same assumption as `permissions`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from src.agent.paraview_owner import active_project_id, set_active_project
from src.agent.session_manager import SessionWorker

logger = logging.getLogger(__name__)

# session_id -> worker
_workers: dict[str, SessionWorker] = {}

# Route-layer driver for autonomous (wake-up) turns. Registered by the API
# module at import via `set_autonomous_turn_handler` — kept as a hook here so
# the worker can reach it without the registry importing routes (which would
# be a cycle: routes already imports this module).
_autonomous_turn_handler: Callable | None = None


def set_autonomous_turn_handler(fn: Callable) -> None:
    global _autonomous_turn_handler
    _autonomous_turn_handler = fn


# ── lookup ──────────────────────────────────────────────────────────────
def get(session_id: str) -> SessionWorker | None:
    return _workers.get(session_id)


def get_by_project(project_id: str) -> SessionWorker | None:
    for w in _workers.values():
        if w.project_id == project_id:
            return w
    return None


async def get_or_create(
    session_id: str, factory: Callable[[], SessionWorker]
) -> SessionWorker:
    """Return the live worker for this session, or build+start one.

    `factory` must construct a SessionWorker (with
    `on_state_change=on_worker_state_change`). It is only called on a miss.
    """
    w = _workers.get(session_id)
    if w is not None:
        return w
    w = factory()
    _workers[session_id] = w
    await w.start()
    # Phase-transition cleanup: a project has exactly one active
    # phase-session at a time, so creating a new-phase worker means any
    # sibling worker for the same project (the previous phase, now idle
    # after the phase advanced) can be closed.
    if w.project_id is not None:
        for sid, other in list(_workers.items()):
            if sid != session_id and other.project_id == w.project_id:
                _workers.pop(sid, None)
                try:
                    await other.close()
                except Exception:
                    logger.warning("error closing sibling worker", exc_info=True)
    return w


# ── interrupt ───────────────────────────────────────────────────────────
async def interrupt_project(project_id: str) -> bool:
    """Interrupt the active turn of a project's worker. False if none."""
    w = get_by_project(project_id)
    if w is None:
        return False
    await w.interrupt()
    return True


# ── lifecycle ───────────────────────────────────────────────────────────
def on_worker_state_change(worker: SessionWorker) -> None:
    """Sync callback the worker fires at turn-end / task-completion.

    Schedules an async close-check (can't await in the worker's callback).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_maybe_close(worker))


def on_autonomous_turn(worker: SessionWorker, queue) -> None:
    """Sync callback the worker fires when it starts a turn the user didn't
    request (a background-task / Monitor wake-up re-invoked the agent).

    Hands the fresh turn `queue` to the route layer so it attaches a buffer
    + persistence task — the wake-up turn is then streamed and saved exactly
    like a user turn. No-op until the API module registers a handler.
    """
    if _autonomous_turn_handler is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_autonomous_turn_handler(worker, queue))


async def on_active_project_changed(new_active: str | None) -> None:
    """Frontend switched the active project. Set it and reap idle others."""
    set_active_project(new_active)
    # Switch-away trigger: any non-active, idle, taskless worker can go.
    for w in list(_workers.values()):
        await _maybe_close(w)


async def close_session(session_id: str) -> None:
    """Explicit close (phase advance / project delete). Unconditional."""
    w = _workers.pop(session_id, None)
    if w is not None:
        await w.close()


async def close_project(project_id: str) -> None:
    """Explicit close of whatever session a project currently holds."""
    for sid, w in list(_workers.items()):
        if w.project_id == project_id:
            _workers.pop(sid, None)
            await w.close()


async def shutdown() -> None:
    """Close every worker (server shutdown)."""
    workers = list(_workers.items())
    _workers.clear()
    for _sid, w in workers:
        try:
            await w.close()
        except Exception:
            logger.warning("error closing worker on shutdown", exc_info=True)


async def _maybe_close(worker: SessionWorker) -> None:
    """Close-check: never the active project, never while busy.

    Fail-safe: if no active project is known yet (e.g. before the frontend
    has called /activate), close nothing — we can't tell what to protect,
    and wrongly reaping would break worker persistence.
    """
    if active_project_id() is None:
        return
    if worker.project_id is not None and worker.project_id == active_project_id():
        return  # active project — keep alive
    if not worker.is_idle():
        return  # turn running or background task alive
    sid = worker.session_id
    # Only remove if this is still the registered worker for the session.
    if _workers.get(sid) is worker:
        _workers.pop(sid, None)
        await worker.close()
