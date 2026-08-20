"""Unit test for session registry lifecycle / close-check (no SDK)."""

import asyncio

from src.agent import session_registry as reg
from src.agent import paraview_owner as po


class FakeWorker:
    def __init__(self, session_id, project_id, idle=True):
        self.session_id = session_id
        self.project_id = project_id
        self._idle = idle
        self.closed = False
        self.interrupted = False

    def is_idle(self):
        return self._idle

    async def close(self):
        self.closed = True

    async def interrupt(self):
        self.interrupted = True


def _run(coro):
    # Fresh loop per call: a prior pytest-asyncio test can leave the
    # thread's event loop unset, which makes get_event_loop() raise.
    return asyncio.run(coro)


def _reset():
    reg._workers.clear()
    po.set_active_project(None)


def test_never_close_active_project():
    _reset()
    w = FakeWorker("s-A", "A", idle=True)
    reg._workers["s-A"] = w
    po.set_active_project("A")
    _run(reg._maybe_close(w))
    assert not w.closed, "active project's worker must never close"
    assert reg.get("s-A") is w


def test_failsafe_no_active_project_closes_nothing():
    _reset()  # active_project = None
    w = FakeWorker("s-A", "A", idle=True)
    reg._workers["s-A"] = w
    _run(reg._maybe_close(w))
    assert not w.closed, "with no active project set, nothing should close"
    assert reg.get("s-A") is w


def test_close_non_active_idle():
    _reset()
    w = FakeWorker("s-A", "A", idle=True)
    reg._workers["s-A"] = w
    po.set_active_project("B")  # A is not active
    _run(reg._maybe_close(w))
    assert w.closed, "non-active idle worker should close"
    assert reg.get("s-A") is None


def test_keep_non_active_busy():
    _reset()
    w = FakeWorker("s-A", "A", idle=False)  # has a turn or running task
    reg._workers["s-A"] = w
    po.set_active_project("B")
    _run(reg._maybe_close(w))
    assert not w.closed, "busy worker must not close even if non-active"
    assert reg.get("s-A") is w


def test_switch_away_reaps_idle_keeps_active_and_busy():
    _reset()
    a = FakeWorker("s-A", "A", idle=True)    # idle, will be switched away from
    b = FakeWorker("s-B", "B", idle=True)    # becomes active
    c = FakeWorker("s-C", "C", idle=False)   # busy (running solver)
    reg._workers.update({"s-A": a, "s-B": b, "s-C": c})
    po.set_active_project("A")

    _run(reg.on_active_project_changed("B"))  # user switches A -> B

    assert po.active_project_id() == "B"
    assert a.closed, "A was idle and switched away -> should close"
    assert not b.closed, "B is now active -> keep"
    assert not c.closed, "C has a running task -> keep"


def test_close_session_unconditional():
    _reset()
    w = FakeWorker("s-A", "A", idle=False)   # busy, but explicit close wins
    reg._workers["s-A"] = w
    po.set_active_project("A")               # even active
    _run(reg.close_session("s-A"))
    assert w.closed
    assert reg.get("s-A") is None


def test_interrupt_routes_to_project_worker():
    _reset()
    w = FakeWorker("s-A", "A")
    reg._workers["s-A"] = w
    assert _run(reg.interrupt_project("A")) is True
    assert w.interrupted
    assert _run(reg.interrupt_project("nonexistent")) is False


def test_get_or_create_only_builds_on_miss():
    _reset()
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        w = FakeWorker("s-A", "A")
        # get_or_create calls .start(); give the fake one.
        async def start():
            return None
        w.start = start
        return w

    w1 = _run(reg.get_or_create("s-A", factory))
    w2 = _run(reg.get_or_create("s-A", factory))
    assert w1 is w2
    assert calls["n"] == 1, "factory should only run on a miss"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok: {name}")
    print("PASS — session registry lifecycle correct")
