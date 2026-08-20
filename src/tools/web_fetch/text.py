"""Text path (spec §4.6): decode, normalize newlines, write ``content.txt``."""

from __future__ import annotations

from pathlib import Path

from src.tools.web_fetch.fetcher import FetchOutcome
from src.tools.web_fetch.schemas import DocMetadata, FetchResult

# Below this, also inline the content so the agent skips a Read round-trip (plan §3).
SMALL_DOC_LINES = 400


async def process(
    outcome: FetchOutcome, entry: Path, accessed: str, source_url: str
) -> FetchResult:
    text = (outcome.raw or b"").decode(outcome.encoding or "utf-8", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    path = entry / "content.txt"
    path.write_text(text)

    line_count = text.count("\n") + 1 if text else 0
    return FetchResult(
        status="ok",
        content_type="text",
        content_path=str(path.resolve()),
        content_inline=text if line_count <= SMALL_DOC_LINES else None,
        metadata=DocMetadata(
            source_url=source_url,
            resolved_url=outcome.resolved_url,
            accessed=accessed,
        ),
        line_count=line_count,
        est_tokens=len(text) // 4,
    )
