"""``web_fetch`` tool package — a deterministic fetch → normalize → handoff reader.

A single tool (``web_fetch``) backed by its own MCP server. The tool object is
built **per turn** by ``make_web_fetch(cache_root)`` so it can be bound to the
calling phase's project cache dir — see ``src/tools/__init__.py`` for the
``build_tooling`` injection seam. Model-facing id: ``mcp__web_fetch__web_fetch``.
"""

from src.tools.web_fetch.tool import make_web_fetch

WEB_FETCH_MCP_SERVER_NAME = "web_fetch"
WEB_FETCH_TOOL = "web_fetch"

__all__ = [
    "WEB_FETCH_MCP_SERVER_NAME",
    "WEB_FETCH_TOOL",
    "make_web_fetch",
]
