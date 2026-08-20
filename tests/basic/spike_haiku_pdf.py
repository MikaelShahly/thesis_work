"""SPIKE (throwaway): can we hand a PDF to Haiku as a native `document` block
through the Agent SDK under subscription auth, and does Haiku read the figures?

Two questions this answers:
  1. Feasibility — does a no-tool ``query()`` accept a base64 PDF document block
     when ANTHROPIC_API_KEY is stripped (the production auth path)?
  2. Quality — asked for values that live INSIDE figures (Fig 3 Cl/Cd inset
     tables, Fig 5 spectra peaks, Fig 13 fit equations), how accurate is Haiku?

Run: .venv/bin/python tests/basic/spike_haiku_pdf.py
Delete after evaluating.
"""

from __future__ import annotations

import asyncio
import base64
import os
from pathlib import Path
from typing import Any

# Replicate production auth: strip API keys so the SDK uses the Claude Code
# subscription (src/api/app.py does the same at startup).
for _k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
    os.environ.pop(_k, None)

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

PDF = Path(__file__).resolve().parents[2] / "NACA0015 paper.pdf"

INTENT = """You are given a CFD validation paper as a PDF. Extract the
following SPECIFIC numbers exactly as printed — several live inside figures, so
read the figure images, not just the body text. If a value is unreadable, say
"unreadable" rather than guessing.

1. Chord Reynolds number, excitation frequency (Hz), the momentum-coefficient
   range, and the angles of attack studied.
2. Figure 3 inset tables — for EACH of the six panels (a)-(f), the experimental
   and numerical Cl and Cd.
3. Figure 5 — the dominant frequencies (Hz) marked by the arrows in panels
   (a), (b), (c), (d).
4. Figure 13(a) — the linear-fit and quadratic-fit equations for the mean lift
   increment at alpha = 0 degrees.
"""


async def main() -> None:
    pdf_b64 = base64.standard_b64encode(PDF.read_bytes()).decode()
    print(f"PDF: {PDF.name}  ({PDF.stat().st_size/1e6:.2f} MB, "
          f"~{len(pdf_b64)/1e6:.2f} MB base64)\n")

    blocks = [
        {"type": "text", "text": INTENT},
        {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": pdf_b64,
            },
        },
    ]

    async def prompt():
        yield {
            "type": "user",
            "message": {"role": "user", "content": blocks},
            "parent_tool_use_id": None,
            "session_id": "",
        }

    options = ClaudeAgentOptions(
        model="claude-haiku-4-5",
        allowed_tools=[],          # no tools — pure one-shot read
        max_turns=1,
        system_prompt="You are a meticulous CFD literature analyst.",
    )

    out: list[str] = []
    result: ResultMessage | None = None
    async for msg in query(prompt=prompt(), options=options):
        if isinstance(msg, AssistantMessage):
            for b in msg.content:
                if isinstance(b, TextBlock):
                    out.append(b.text)
        elif isinstance(msg, ResultMessage):
            result = msg

    print("=" * 70)
    print("HAIKU OUTPUT")
    print("=" * 70)
    print("\n".join(out) if out else "(no text returned)")
    if result is not None:
        print("\n" + "=" * 70)
        cost = getattr(result, "total_cost_usd", None)
        usage = getattr(result, "usage", None)
        print(f"is_error={getattr(result, 'is_error', '?')}  "
              f"cost_usd={cost}  usage={usage}")


if __name__ == "__main__":
    asyncio.run(main())
