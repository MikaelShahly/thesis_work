"""Unit tests for _TurnBuffer (live-only vs replayable events).

Guards the race that broke the live approve-spec path: a live-only
transition marker (replay=False) pushed *before* the client subscribes
must still reach the first subscriber, but must NOT be replayed to a
re-attaching client (which would duplicate the phase divider).
"""

import asyncio

from src.api.routes import _TurnBuffer


async def _drain(buf):
    out = []
    async for ev in buf.stream():
        out.append(ev["event"] if isinstance(ev, dict) else ev)
    return out


def _run(coro):
    # Fresh loop per call: a prior pytest-asyncio test can leave the
    # thread's event loop unset, which makes get_event_loop() raise.
    return asyncio.run(coro)


def test_live_only_reaches_first_subscriber_despite_race():
    buf = _TurnBuffer()
    buf.push({"event": "spec_approved"}, replay=False)  # pushed before any subscriber
    buf.push({"event": "text1"}, replay=True)
    buf.push({"event": "text2"}, replay=True)
    buf.close()
    first = _run(_drain(buf))
    assert first == ["spec_approved", "text1", "text2"], first


def test_live_only_not_replayed_to_reattacher():
    buf = _TurnBuffer()
    buf.push({"event": "spec_approved"}, replay=False)
    buf.push({"event": "text1"}, replay=True)
    buf.close()
    _ = _run(_drain(buf))            # first subscriber (live) consumes pending
    reattach = _run(_drain(buf))     # second subscriber (re-attach)
    assert reattach == ["text1"], reattach  # no spec_approved replay -> no dup divider


def test_live_only_delivered_when_subscriber_present():
    # If a subscriber is already attached, a live-only push goes straight to it.
    buf = _TurnBuffer()

    async def scenario():
        out = []
        agen = buf.stream()
        # prime the subscriber (registers its queue + snapshots empty backlog)
        task = asyncio.ensure_future(_collect(agen, out))
        await asyncio.sleep(0)  # let stream() register
        buf.push({"event": "live_marker"}, replay=False)
        buf.push({"event": "text1"}, replay=True)
        buf.close()
        await task
        return out

    async def _collect(agen, out):
        async for ev in agen:
            out.append(ev["event"])

    out = _run(scenario())
    assert "live_marker" in out and "text1" in out, out


def test_reset_clears_prior_turn_from_replay():
    # Multi-turn (handoff -> kickoff): after the handoff turn completes and
    # reset() is called, a re-attaching client must replay ONLY the kickoff —
    # not the finished handoff turn (which is in history) nor its stale
    # turn_complete, nor the live-only divider.
    buf = _TurnBuffer()
    buf._had_subscriber = True  # the live client already attached earlier
    buf.push({"event": "handoff_text"}, replay=True)
    buf.push({"event": "turn_complete"}, replay=True)   # handoff turn end
    buf.reset()                                          # turn boundary
    buf.push({"event": "phase_transitioned"}, replay=False)  # live-only divider
    buf.push({"event": "kickoff_text"}, replay=True)
    buf.close()
    reattach = _run(_drain(buf))
    assert reattach == ["kickoff_text"], reattach  # only the current turn


if __name__ == "__main__":
    test_live_only_reaches_first_subscriber_despite_race()
    test_live_only_not_replayed_to_reattacher()
    test_live_only_delivered_when_subscriber_present()
    test_reset_clears_prior_turn_from_replay()
    print("PASS — _TurnBuffer live-only/replay/reset semantics correct")
