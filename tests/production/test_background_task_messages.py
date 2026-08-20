"""Phase-0 verification: do background-task lifecycle messages actually fire?

Drives a persistent ClaudeSDKClient, has the agent launch a real
`run_in_background` bash command, then KEEPS reading the message stream
after the turn ends (the agent goes idle while the job keeps running).

We are checking three things against the bundled CLI (2.1.119):
  1. The agent actually backgrounds the command (tool_use with
     run_in_background=true).
  2. A TaskStartedMessage arrives when it starts.
  3. A TaskNotificationMessage arrives when it finishes — *while the
     agent is idle* (turn already ended). This is the signal our
     idle / idle-with-background-task detection depends on.

Run:  uv run python tests/production/test_background_task_messages.py
"""

import anyio

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    SystemMessage,
    ResultMessage,
    TaskStartedMessage,
    TaskProgressMessage,
    TaskNotificationMessage,
    TextBlock,
    ToolUseBlock,
)

PROMPT = (
    "Run EXACTLY this command using the Bash tool with run_in_background "
    "set to true, then immediately end your turn without waiting for it:\n\n"
    "    bash -c 'for i in $(seq 1 12); do echo tick $i; sleep 1; done; echo FINISHED'\n\n"
    "Do not poll it, do not call BashOutput. Just reply with one short "
    "sentence confirming you started it in the background."
)

OVERALL_TIMEOUT_S = 70


async def main() -> None:
    options = ClaudeAgentOptions(
        model="claude-haiku-4-5-20251001",
        allowed_tools=["Bash", "BashOutput"],
        permission_mode="default",
    )

    saw_bg_tool = False
    started = []
    notifications = []
    turn_ended = False

    print(">>> connecting persistent client...")
    async with ClaudeSDKClient(options=options) as client:
        await client.query(PROMPT)
        print(">>> query sent; reading stream (continuous)...\n")

        with anyio.move_on_after(OVERALL_TIMEOUT_S):
            async for msg in client.receive_messages():
                kind = type(msg).__name__

                if isinstance(msg, AssistantMessage):
                    for b in msg.content:
                        if isinstance(b, ToolUseBlock):
                            bg = bool(b.input.get("run_in_background"))
                            print(f"[tool_use] {b.name}  run_in_background={bg}")
                            print(f"            input={b.input}")
                            if b.name == "Bash" and bg:
                                saw_bg_tool = True
                        elif isinstance(b, TextBlock):
                            print(f"[assistant] {b.text.strip()[:140]}")

                elif isinstance(msg, TaskStartedMessage):
                    print(f"[TASK STARTED]      {msg!r}")
                    started.append(msg)

                elif isinstance(msg, TaskProgressMessage):
                    print(f"[TASK PROGRESS]     {msg!r}")

                elif isinstance(msg, TaskNotificationMessage):
                    print(f"[TASK NOTIFICATION] {msg!r}")
                    notifications.append(msg)
                    break  # got the completion signal — done

                elif isinstance(msg, ResultMessage):
                    turn_ended = True
                    print(
                        f"[result] turn ended (subtype={msg.subtype}). "
                        f"agent now IDLE; waiting for task completion...\n"
                    )

                elif isinstance(msg, SystemMessage):
                    print(f"[system] subtype={msg.subtype}")

                else:
                    print(f"[{kind}]")

    print("\n================= SUMMARY =================")
    print(f"agent backgrounded the command : {saw_bg_tool}")
    print(f"turn ended (went idle)         : {turn_ended}")
    print(f"TaskStartedMessage count       : {len(started)}")
    print(f"TaskNotificationMessage count  : {len(notifications)}")
    if notifications:
        n = notifications[0]
        print(f"  notification fields          : {n!r}")
    verdict = (
        saw_bg_tool
        and len(started) >= 1
        and len(notifications) >= 1
    )
    print(f"\nVERDICT: {'PASS — task lifecycle messages work' if verdict else 'FAIL — see trace above'}")


if __name__ == "__main__":
    anyio.run(main)
