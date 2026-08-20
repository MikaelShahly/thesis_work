"""web_fetch — wiring: build_tooling dispatch, cache keys, file-tracker prune.

All offline. Proves the injection seam (plan §3) and that the cache dir stays
invisible to the file-write tracker (plan §4)."""

from __future__ import annotations

import os

from src.agent.hooks import _scan_project
from src.tools import build_tooling, translate_tool_names
from src.tools.web_fetch import cache as C
from src.tools.web_fetch.schemas import DocMetadata, FetchResult


def test_translate_maps_web_fetch_to_mcp_name():
    assert translate_tool_names(["web_fetch", "WebSearch"]) == [
        "mcp__web_fetch__web_fetch",
        "WebSearch",
    ]


def test_build_tooling_registers_bound_server_and_gates(tmp_path):
    visible, allowed, servers = build_tooling(
        ["present_specification", "WebSearch", "web_fetch"],
        ["present_specification", "WebSearch"],
        project_dir=tmp_path,
    )
    assert "mcp__web_fetch__web_fetch" in visible
    assert "mcp__web_fetch__web_fetch" not in allowed  # gated, not auto-approved
    assert "web_fetch" in servers


def test_build_tooling_skips_web_fetch_without_project_dir():
    _, _, servers = build_tooling(["web_fetch"], [])
    assert "web_fetch" not in servers


def test_normalize_url_lowercases_host_strips_fragment_keeps_query():
    assert C.normalize_url("HTTPS://Example.COM/Path?q=1#frag") == "https://example.com/Path?q=1"
    assert C.cache_key("https://x.com/a#one") == C.cache_key("https://x.com/a#two")
    assert C.cache_key("https://x.com/a?b=1") != C.cache_key("https://x.com/a?b=2")


def test_cache_write_load_and_ttl(tmp_path):
    url = "https://x.com/doc"
    res = FetchResult(status="ok", content_type="text", metadata=DocMetadata(source_url=url))
    assert C.load_cached(tmp_path, url) is None  # nothing yet
    C.prepare_entry(tmp_path, url)
    C.write_meta(tmp_path, url, res)
    assert C.load_cached(tmp_path, url).status == "ok"  # fresh hit

    meta = C.entry_dir(tmp_path, url) / C.META_NAME
    old = os.stat(meta).st_mtime - 2 * 24 * 3600  # backdate 2 days
    os.utime(meta, (old, old))
    assert C.load_cached(tmp_path, url) is None  # stale → miss (re-fetch)


def test_scan_project_prunes_hidden_dirs(tmp_path):
    (tmp_path / "Case").mkdir()
    (tmp_path / "Case" / "U").write_text("x")
    (tmp_path / ".webcache" / "abc" / "figures").mkdir(parents=True)
    (tmp_path / ".webcache" / "abc" / "content.md").write_text("y")
    (tmp_path / ".webcache" / "abc" / "meta.json").write_text("{}")
    scanned = {str(p) for p in _scan_project(tmp_path)}
    assert scanned == {"Case/U"}  # nothing under .webcache leaks to file_written
