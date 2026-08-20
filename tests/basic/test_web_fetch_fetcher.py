"""web_fetch — fetch core + safety (basic, offline via httpx.MockTransport)."""

from __future__ import annotations

import httpx
import pytest

from src.tools.web_fetch import fetcher
from src.tools.web_fetch.fetcher import (
    _host_is_safe,
    _same_host,
    fetch,
    resolve_content_type,
)

ALLOW = ("example.com", "other.com")  # bypass SSRF DNS so tests stay offline

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


# ── pure helpers ─────────────────────────────────────────────────────────────
def test_ssrf_guard_rejects_private_and_meta_ip():
    for bad in ("127.0.0.1", "10.0.0.1", "192.168.1.1", "169.254.169.254", "::1"):
        assert _host_is_safe(bad) is False
    assert _host_is_safe("8.8.8.8") is True  # public IP literal (no DNS)
    assert _host_is_safe("127.0.0.1", allowlist=("127.0.0.1",)) is True  # allowlist


def test_content_type_sniff_magic_then_header_then_ext():
    assert resolve_content_type(b"%PDF-1.7\n...", "", "http://x/f") == "pdf"
    assert resolve_content_type(_PNG, "image/png", "http://x/i.png") == "binary"
    assert resolve_content_type(b"<!doctype html><html>", "text/html", "http://x") == "html"
    assert resolve_content_type(b"<html><body>", "", "http://x/page") == "html"  # sniff
    assert resolve_content_type(b"col1,col2\n1,2\n", "text/plain", "http://x/d.csv") == "text"


def test_same_host_canonicalization():
    assert _same_host("http://x.com/a", "https://x.com/b") is True  # scheme
    assert _same_host("https://x.com", "https://www.x.com/y") is True  # www
    assert _same_host("https://x.com", "https://y.com") is False


# ── mocked fetch statuses ────────────────────────────────────────────────────
def _transport(target: httpx.Response, *, robots_body="User-agent: *\nAllow: /"):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots_body)
        return target
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_oversize_by_content_length(monkeypatch):
    monkeypatch.setattr(fetcher, "BYTE_CEILING", 10)
    t = _transport(httpx.Response(200, content=b"x" * 100, headers={"content-type": "text/html"}))
    out = await fetch("https://example.com/big", allowlist=ALLOW, transport=t)
    assert out.status == "oversize" and out.content_length == 100


@pytest.mark.asyncio
async def test_binary_short_circuit(monkeypatch):
    t = _transport(httpx.Response(200, content=_PNG, headers={"content-type": "image/png"}))
    out = await fetch("https://example.com/fig.png", allowlist=ALLOW, transport=t)
    assert out.status == "binary_skipped"


@pytest.mark.asyncio
async def test_cross_host_redirect_not_followed():
    t = _transport(httpx.Response(301, headers={"location": "https://other.com/moved"}))
    out = await fetch("https://example.com/old", allowlist=ALLOW, transport=t)
    assert out.status == "redirected" and out.redirect_url == "https://other.com/moved"


@pytest.mark.asyncio
async def test_http_403_is_fetch_error_with_hint():
    t = _transport(httpx.Response(403))
    out = await fetch("https://example.com/blocked", allowlist=ALLOW, transport=t)
    assert out.status == "fetch_error" and "403" in out.error and "JS challenge" in out.error


@pytest.mark.asyncio
async def test_blocked_by_robots():
    t = _transport(httpx.Response(200, text="ok"), robots_body="User-agent: *\nDisallow: /")
    out = await fetch("https://example.com/page", allowlist=ALLOW, transport=t)
    assert out.status == "blocked_by_robots"


@pytest.mark.asyncio
async def test_ok_html_passthrough():
    t = _transport(httpx.Response(200, content=b"<html><body>hi</body></html>",
                                  headers={"content-type": "text/html"}))
    out = await fetch("https://example.com/p", allowlist=ALLOW, transport=t)
    assert out.status == "ok" and out.content_type == "html" and out.raw
