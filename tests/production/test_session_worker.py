"""Phase-1 isolation test for SessionWorker.

Proves the core of the persistent-worker design without the FastAPI /
frontend stack:

  1. Turn 1 backgrounds a job and ENDS (turn_complete) — agent goes idle.
  2. running_tasks is populated from TaskStartedMessage.
  3. While idle (between turns), the continuous receive loop catches the
     TaskNotificationMessage and running_tasks empties — proving the loop
     keeps running and the subprocess persists.
  4. Turn 2 runs on the SAME worker/client (no reconnect) — proving
     persistence across turns.

Run:  uv run python tests/production/test_session_worker.py
"""

import asyncio
import time
from pathlib import Path

from src.agent.session_manager import SessionWorker

BG_PROMPT = (
    "Run EXACTLY this with the Bash tool, run_in_background=true, then end "
    "your turn immediately without waiting:\n\n"
    "    bash -c 'for i in $(seq 1 12); do echo $i; sleep 1; done; echo DONE'\n\n"
    "Reply with one short sentence confirming you started it."
)


async def drain(worker: SessionWorker, user_message: str) -> dict:
    """Run one turn, return a summary of what was seen."""
    seen = {"turn_complete": False, "text": "", "tool_use": []}
    async for ev in worker.submit_turn(user_message):
        if ev.type == "turn_complete":
            seen["turn_complete"] = True
        elif ev.type == "text_delta":
            seen["text"] += ev.data.get("content", "")
        elif ev.type == "tool_input":
            seen["tool_use"].append(ev.data.get("tool"))
    return seen


async def main() -> None:
    worker = SessionWorker(
        session_id="test-session",
        system_prompt="You are a test agent. Follow instructions exactly.",
        model="claude-haiku-4-5-20251001",
        tools=["Bash", "BashOutput"],
        allowed_tools=["Bash", "BashOutput"],
        mcp_servers={},
        resume_session_id=None,
        max_turns=20,
        project_dir=Path("/tmp"),
        project_id="test-project",
    )

    print(">>> starting worker (connect + continuous loop)...")
    await worker.start()
    client_obj_id = id(worker.client)

    # ── Turn 1: background a job, end the turn ──
    print(">>> TURN 1: background a job")
    t1 = await drain(worker, BG_PROMPT)
    print(f"    turn_complete={t1['turn_complete']} tools={t1['tool_use']}")
    print(f"    turn_active={worker.turn_active}  running_tasks={worker.running_tasks}")

    assert t1["turn_complete"], "turn 1 never completed"
    assert worker.turn_active is False, "worker should be idle after turn 1"
    assert len(worker.running_tasks) >= 1, "background task not tracked (TaskStartedMessage)"

    # ── While idle: continuous loop must catch TaskNotificationMessage ──
    print(">>> IDLE: waiting for background task to finish (loop must catch it)...")
    deadline = time.monotonic() + 40
    while worker.running_tasks and time.monotonic() < deadline:
        await asyncio.sleep(0.5)
    print(f"    running_tasks after wait = {worker.running_tasks}")
    assert not worker.running_tasks, "TaskNotificationMessage not caught while idle"
    assert worker.is_idle(), "worker should be fully idle now"

    # ── Turn 2: same worker/client, no reconnect ──
    print(">>> TURN 2: second turn on the SAME persistent client")
    t2 = await drain(worker, "Reply with exactly the single word: PONG")
    print(f"    turn_complete={t2['turn_complete']} text={t2['text'].strip()[:60]!r}")
    assert t2["turn_complete"], "turn 2 never completed"
    assert id(worker.client) == client_obj_id, "client was replaced — not persistent!"

    await worker.close()

    print("\n================= SUMMARY =================")
    print("turn 1 ended (went idle)          : True")
    print("background task tracked (started) : True")
    print("completion caught while idle      : True")
    print("turn 2 ran on same client         : True")
    print("\nVERDICT: PASS — SessionWorker persists across turns and tracks tasks cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
