"""Inspect what `task_updated` (and any TaskProgressMessage) actually is.

Backgrounds a longer job and prints, with elapsed timestamps, the full
data of every system / task-lifecycle message — so we can see the
cadence (one tick? steady progress?) and the payload (does it carry
output bytes / progress / status?).

Run:  uv run python tests/production/test_task_updated_inspect.py
"""

import time
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
    "set to true, then immediately end your turn without waiting:\n\n"
    "    bash -c 'for i in $(seq 1 20); do echo line $i; sleep 1; done; echo FINISHED'\n\n"
    "Do not poll it. Just reply with one short sentence."
)

OVERALL_TIMEOUT_S = 60


async def main() -> None:
    options = ClaudeAgentOptions(
        model="claude-haiku-4-5-20251001",
        allowed_tools=["Bash", "BashOutput"],
        permission_mode="default",
    )
    t0 = time.monotonic()

    def stamp() -> str:
        return f"t+{time.monotonic() - t0:5.1f}s"

    async with ClaudeSDKClient(options=options) as client:
        await client.query(PROMPT)
        print(f"{stamp()} query sent\n")
        with anyio.move_on_after(OVERALL_TIMEOUT_S):
            async for msg in client.receive_messages():
                if isinstance(msg, AssistantMessage):
                    for b in msg.content:
                        if isinstance(b, ToolUseBlock):
                            print(f"{stamp()} [tool_use] {b.name} bg={b.input.get('run_in_background')}")
                elif isinstance(msg, ResultMessage):
                    print(f"{stamp()} [result] turn ended (idle now)\n")
                elif isinstance(msg, TaskStartedMessage):
                    print(f"{stamp()} [TaskStartedMessage] {msg!r}\n")
                elif isinstance(msg, TaskProgressMessage):
                    print(f"{stamp()} [TaskProgressMessage] {msg!r}\n")
                elif isinstance(msg, TaskNotificationMessage):
                    print(f"{stamp()} [TaskNotificationMessage] status={msg.status}\n")
                    break
                elif isinstance(msg, SystemMessage):
                    # The interesting one: print subtype + full data.
                    print(f"{stamp()} [SystemMessage subtype={msg.subtype}]")
                    print(f"          data={msg.data}\n")


if __name__ == "__main__":
    anyio.run(main)
