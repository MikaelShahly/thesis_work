"""The ``web_fetch`` tool: factory + deterministic pipeline (plan §2, §3, §5).

``make_web_fetch(cache_root)`` returns a fresh ``SdkMcpTool`` whose handler closes
over a per-project cache dir — this is how the in-process tool learns the project
folder (plan §0/§3), since the ``@tool`` handler only ever receives ``args``. The
pipeline is fetch → dispatch → (pdf | html | text) → assemble; it **never raises**,
turning every failure into a structured ``FetchResult`` status.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

from src.tools.web_fetch import cache as cache_mod
from src.tools.web_fetch import html as html_mod
from src.tools.web_fetch import pdf as pdf_mod
from src.tools.web_fetch import text as text_mod
from src.tools.web_fetch.fetcher import fetch
from src.tools.web_fetch.schemas import DocMetadata, FetchResult, WebFetchInput

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "The URL to fetch (use after web_search has found it).",
        },
        "force_raw": {
            "type": "boolean",
            "description": (
                "Skip trafilatura main-content extraction and dump a fuller "
                "cleaned-DOM markdown. Use only if a normal fetch under-extracts."
            ),
        },
    },
    "required": ["url"],
}

_DESCRIPTION = (
    "Fetch a web URL, normalize it to a local file, and hand back a navigation map. "
    "Use it AFTER web_search has found a URL — search finds, this fetches + stages "
    "for Read.\n\n"
    "It does NOT summarize and does NOT return the content in the tool result. "
    "Instead it stages the document on disk and returns a descriptor: a "
    "`content_path` to Read (PDFs as page images+text; HTML/text as markdown), a "
    "typed `links` list (full-DOM harvest — data files, citations, internal, "
    "external), a `toc` (page- or line-anchored, to aim your Read calls), a "
    "`figures` index (downloaded images by absolute local path), and `metadata`. "
    "Read `content_path` to see the actual content; if `content_inline` is set the "
    "doc was small and is included.\n\n"
    "Data files in `links` (type=data, e.g. .dat/.csv/.vtk/.stl/.msh) are surfaced "
    "but NOT downloaded — fetch any you need yourself with Bash (curl).\n\n"
    "Read-only. Respects robots.txt and refuses private/loopback hosts. Returns a "
    "structured `status`: `ok`; `redirected` (cross-host — re-call with "
    "`redirect_url`); `blocked_by_robots`; `oversize`; `binary_skipped` (a non-PDF "
    "binary — use the link instead); `fetch_error`/`parse_error` (see `error`)."
    "WHEN TO USE — web_search and web_fetch are a two-stage pipeline. A web_search "
    "result gives you a `Links` list (title + URL) plus a tool-generated prose "
    "summary. The summary is a useful, valid overview — read it to orient yourself "
    "and to judge which links are worth pursuing. But it's a digest, not a citable "
    "source: it blends multiple hits together and drops per-claim attribution, so "
    "don't ground anything important on it directly. Before you rely on a source, "
    "cite it, or extract exact data — a value, correlation, coefficient, mesh "
    "setting, boundary condition, or a paper's conclusions — call web_fetch on that "
    "specific link to stage the full document and Read it yourself. The summary "
    "tells you roughly what's out there; the fetched document is what you actually "
    "build your answer on.\n\n"
)


async def run_pipeline(args: dict[str, Any], cache_root: Path) -> FetchResult:
    raw_url = str((args or {}).get("url", "")).strip()
    try:
        inp = WebFetchInput(**(args or {}))
    except Exception as e:
        return FetchResult(
            status="fetch_error",
            metadata=DocMetadata(source_url=raw_url),
            error=f"Invalid input: {e}",
        )

    cached = cache_mod.load_cached(cache_root, inp.url)
    if cached is not None:
        return cached

    outcome = await fetch(inp.url)
    accessed = date.today().isoformat()

    if outcome.status != "ok":
        # Failures/determinations are not cached, so a retry within the TTL works.
        return FetchResult(
            status=outcome.status,
            metadata=DocMetadata(
                source_url=inp.url,
                resolved_url=outcome.resolved_url,
                accessed=accessed,
            ),
            redirect_url=outcome.redirect_url,
            content_length=outcome.content_length,
            error=outcome.error,
        )

    entry = cache_mod.prepare_entry(cache_root, inp.url)
    try:
        if outcome.content_type == "pdf":
            result = await pdf_mod.process(outcome, entry, accessed, inp.url)
        elif outcome.content_type == "html":
            result = await html_mod.process(
                outcome, entry, accessed, inp.url, force_raw=inp.force_raw
            )
        else:
            result = await text_mod.process(outcome, entry, accessed, inp.url)
    except Exception as e:
        return FetchResult(
            status="parse_error",
            content_type=outcome.content_type,
            metadata=DocMetadata(
                source_url=inp.url,
                resolved_url=outcome.resolved_url,
                accessed=accessed,
            ),
            error=f"{type(e).__name__}: {e}",
        )

    cache_mod.write_meta(cache_root, inp.url, result)
    return result


def make_web_fetch(cache_root: Path):
    """Build a ``web_fetch`` SdkMcpTool bound to ``cache_root`` (per-project)."""

    @tool("web_fetch", _DESCRIPTION, _INPUT_SCHEMA)
    async def web_fetch(args: dict[str, Any]) -> dict[str, Any]:
        result = await run_pipeline(args, cache_root)
        # The access scaffold (Read hint + nav arrays) only applies when content
        # was staged. On any non-ok status nothing is staged, so drop it: the
        # result is just status + error + metadata.
        exclude = (
            None
            if result.status == "ok"
            else {"usage", "toc", "links", "figures", "tables"}
        )
        return {
            "content": [
                {
                    "type": "text",
                    "text": result.model_dump_json(exclude_none=True, exclude=exclude),
                }
            ],
            "is_error": result.status in ("fetch_error", "parse_error"),
        }

    return web_fetch
