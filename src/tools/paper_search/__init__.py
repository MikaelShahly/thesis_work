"""``paper_search`` tool package — academic literature search with direct,
fetchable open-access PDF links.

A single tool (``paper_search``) backed by its own MCP server. It fans out to
OpenAlex, arXiv, NASA NTRS, and Semantic Scholar (best-effort), merges + dedups,
and returns candidates whose ``pdf_url`` feeds straight into the existing
``web_fetch`` → ``Read`` pipeline. Unlike ``web_fetch`` it needs no per-project
binding, so the tool object is a static singleton. Model-facing id:
``mcp__paper_search__paper_search``.
"""

from src.tools.paper_search.tool import paper_search

PAPER_SEARCH_MCP_SERVER_NAME = "paper_search"
PAPER_SEARCH_TOOL = "paper_search"

__all__ = [
    "PAPER_SEARCH_MCP_SERVER_NAME",
    "PAPER_SEARCH_TOOL",
    "paper_search",
]
