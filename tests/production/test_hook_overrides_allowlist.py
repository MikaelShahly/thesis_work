"""Does a PreToolUse hook fire + block a tool that is in allowed_tools?

This decides whether we can enforce ParaView single-tenancy regardless
of per-agent allowed_tools config.

Setup: Bash is in allowed_tools (auto-approved -> would NOT hit
can_use_tool). We add a PreToolUse hook on Bash that returns
permissionDecision='deny'. There is NO can_use_tool callback.

  - If the hook FIRES and Bash is BLOCKED -> hooks override the allowlist
    -> we can enforce via a PreToolUse hook even when ParaView is
    allowlisted.
  - If Bash RUNS anyway -> hooks are bypassed by allowed_tools too, and
    the only enforcement is keeping tools out of allowed_tools.

Run:  uv run python tests/production/test_hook_overrides_allowlist.py
"""

import anyio

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    HookMatcher,
    AssistantMessage,
    UserMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)

hook_fired = {"count": 0}


async def deny_bash(input_data, tool_use_id, context):
    hook_fired["count"] += 1
    print(f">>> PreToolUse HOOK FIRED for tool={input_data.get('tool_name')} "
          f"(this proves the hook runs even for an allowlisted tool)")
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "BLOCKED_BY_TEST_HOOK",
        }
    }


PROMPT = (
    "Use the Bash tool to run exactly: echo HELLO_FROM_BASH\n"
    "Then tell me in one sentence what the command output was, or whether "
    "it was blocked."
)


async def main() -> None:
    options = ClaudeAgentOptions(
        model="claude-haiku-4-5-20251001",
        allowed_tools=["Bash"],          # auto-approved: bypasses can_use_tool
        permission_mode="default",
        # NO can_use_tool — so anything blocking Bash can only be the hook.
        hooks={
            "PreToolUse": [HookMatcher(matcher="Bash", hooks=[deny_bash])],
        },
    )

    bash_ran_output = None
    bash_blocked = False

    async with ClaudeSDKClient(options=options) as client:
        await client.query(PROMPT)
        with anyio.move_on_after(60):
            async for msg in client.receive_messages():
                if isinstance(msg, AssistantMessage):
                    for b in msg.content:
                        if isinstance(b, ToolUseBlock):
                            print(f"[tool_use] {b.name} input={b.input}")
                        elif isinstance(b, TextBlock):
                            print(f"[assistant] {b.text.strip()[:160]}")
                elif isinstance(msg, UserMessage):
                    content = msg.content if isinstance(msg.content, list) else []
                    for b in content:
                        if isinstance(b, ToolResultBlock):
                            txt = str(b.content)
                            print(f"[tool_result] is_error={b.is_error} content={txt[:200]}")
                            if "HELLO_FROM_BASH" in txt:
                                bash_ran_output = txt
                            if b.is_error or "BLOCKED_BY_TEST_HOOK" in txt:
                                bash_blocked = True
                elif isinstance(msg, ResultMessage):
                    break

    print("\n================= SUMMARY =================")
    print(f"hook fired (count)     : {hook_fired['count']}")
    print(f"bash produced output   : {bash_ran_output is not None}")
    print(f"bash was blocked       : {bash_blocked}")
    if hook_fired["count"] > 0 and bash_blocked and bash_ran_output is None:
        print("\nVERDICT: PreToolUse HOOK OVERRIDES allowed_tools "
              "-> config-independent enforcement is possible.")
    elif bash_ran_output is not None:
        print("\nVERDICT: hook did NOT block an allowlisted tool "
              "-> must keep tools OUT of allowed_tools to enforce.")
    else:
        print("\nVERDICT: inconclusive — inspect trace above.")


if __name__ == "__main__":
    anyio.run(main)
