"""Fetch core + safety (spec §4.1–4.3, plan §2 Fetcher).

In: a URL. Out: a ``FetchOutcome`` carrying either the raw bytes + resolved type,
or a structured failure status. **Never raises to the caller** — every failure is a
status the tool turns into a ``FetchResult``.

Does, in order: SSRF guard on the initial host, robots.txt, then a streamed GET with
manual redirect handling, the 50 MB byte ceiling (header *and* mid-stream), a
magic-byte content sniff, and a binary short-circuit. Cross-host redirects are not
followed — they are returned for the agent to re-request (kills redirect-SSRF).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

import filetype
import httpx
from protego import Protego

BYTE_CEILING = 50 * 1024 * 1024  # 50 MB single ceiling for all types (plan §3)
TIMEOUT_S = 30.0
ROBOTS_TIMEOUT_S = 10.0
MAX_REDIRECTS = 10
# The product token deliberately avoids substrings that collide with robots.txt
# bot-name rules, which match by SUBSTRING: "fetch", "bot", "crawl", "spider",
# "search" (note "research" contains "search"). e.g. Wikipedia ships
# `User-agent: Fetch / Disallow: /`, which would otherwise match "…web_fetch" and
# wrongly block every Wikipedia article. Keep this clean.
USER_AGENT = "AgenticCFD/0.1 (+https://github.com/agenticcfd; CFD literature reader)"


@dataclass
class FetchOutcome:
    status: str  # ok | redirected | blocked_by_robots | oversize | binary_skipped | fetch_error
    resolved_url: str
    content_type: str | None = None  # pdf | html | text  (when status == ok)
    raw: bytes | None = None
    encoding: str | None = None
    redirect_url: str | None = None  # status == redirected
    content_length: int | None = None  # status in {oversize, binary_skipped}
    error: str | None = None  # status == fetch_error


# ── SSRF guard ──────────────────────────────────────────────────────────────
def _host_is_safe(host: str, allowlist: tuple[str, ...] = ()) -> bool:
    """False if ``host`` resolves to any loopback/private/link-local/reserved IP
    (incl. 169.254.169.254). Allowlisted hosts bypass the check."""
    if host in allowlist:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


async def _host_is_safe_async(host: str, allowlist: tuple[str, ...] = ()) -> bool:
    return await asyncio.to_thread(_host_is_safe, host, allowlist)


# ── robots.txt ──────────────────────────────────────────────────────────────
async def _robots_allows(client: httpx.AsyncClient, url: str) -> bool:
    """Respect robots.txt. 401/403 on the robots fetch → treat as disallowed; any
    other failure (404, network) → allow (no robots = allowed). Spec §4.1."""
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        resp = await client.get(
            robots_url, timeout=ROBOTS_TIMEOUT_S, follow_redirects=True
        )
    except httpx.HTTPError:
        return True
    if resp.status_code in (401, 403):
        return False
    if resp.status_code >= 400:
        return True
    try:
        return Protego.parse(resp.text).can_fetch(url, USER_AGENT)
    except Exception:
        return True


# ── content-type sniff (magic bytes → headers → extension) ──────────────────
def resolve_content_type(raw: bytes, ctype_header: str, url: str) -> str:
    """Return ``pdf`` | ``html`` | ``text`` | ``binary`` from the first bytes,
    headers, then URL extension (most reliable first)."""
    head = raw[:4096]
    if head[:5] == b"%PDF-":
        return "pdf"
    kind = filetype.guess(head)
    if kind is not None and kind.mime != "application/pdf":
        return "binary"  # concrete non-PDF binary (image/archive/font/video/…)

    ch = (ctype_header or "").lower()
    low = head.lstrip().lower()
    if (
        "html" in ch
        or low.startswith(b"<!doctype html")
        or b"<html" in low[:1024]
        or b"<head" in low[:1024]
        or b"<body" in low[:1024]
    ):
        return "html"
    if "pdf" in ch:
        return "pdf"
    path = urlsplit(url).path.lower()
    ext = path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
    if ext in ("html", "htm", "xhtml", "shtml", "php", "asp", "aspx"):
        return "html"
    return "text"


# ── canonical same-host check (scheme/trailing-slash/www-insensitive) ────────
def _same_host(a: str, b: str) -> bool:
    ha = (urlsplit(a).hostname or "").lower().removeprefix("www.")
    hb = (urlsplit(b).hostname or "").lower().removeprefix("www.")
    return ha == hb and ha != ""


# ── main fetch ──────────────────────────────────────────────────────────────
async def fetch(
    url: str,
    allowlist: tuple[str, ...] = (),
    transport: httpx.AsyncBaseTransport | None = None,
) -> FetchOutcome:
    # `transport` is a test seam (httpx.MockTransport); None uses the real network.
    initial_host = urlsplit(url).hostname or ""
    if not initial_host:
        return FetchOutcome("fetch_error", url, error="No host in URL.")
    if not await _host_is_safe_async(initial_host, allowlist):
        return FetchOutcome(
            "fetch_error", url, error=f"SSRF guard: refused host {initial_host!r}."
        )

    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=TIMEOUT_S,
            follow_redirects=False,
            transport=transport,
        ) as client:
            if not await _robots_allows(client, url):
                return FetchOutcome("blocked_by_robots", url)
            return await _stream_with_redirects(client, url, allowlist)
    except httpx.HTTPError as e:
        return FetchOutcome("fetch_error", url, error=f"{type(e).__name__}: {e}")


async def _stream_with_redirects(
    client: httpx.AsyncClient, url: str, allowlist: tuple[str, ...]
) -> FetchOutcome:
    current = url
    for _ in range(MAX_REDIRECTS):
        async with client.stream("GET", current) as resp:
            # Redirects: follow same-host silently; stop on cross-host.
            if resp.is_redirect:
                loc = resp.headers.get("location")
                if not loc:
                    return FetchOutcome("fetch_error", current, error="Redirect w/o Location.")
                target = str(resp.next_request.url) if resp.next_request else loc
                if _same_host(current, target):
                    new_host = urlsplit(target).hostname or ""
                    if not await _host_is_safe_async(new_host, allowlist):
                        return FetchOutcome(
                            "fetch_error", current, error=f"SSRF on redirect to {new_host!r}."
                        )
                    current = target
                    continue
                return FetchOutcome("redirected", current, redirect_url=target)

            if resp.status_code >= 400:
                hint = ""
                if resp.status_code in (401, 403, 429):
                    hint = (
                        " — the server blocked the request, likely bot protection "
                        "or a JS challenge (e.g. Cloudflare). This fetcher cannot run "
                        "JavaScript; use web_search snippets or an alternate source."
                    )
                return FetchOutcome(
                    "fetch_error",
                    current,
                    error=f"HTTP {resp.status_code} {resp.reason_phrase}{hint}",
                )

            # Byte ceiling on the declared length, before reading the body.
            cl_header = resp.headers.get("content-length")
            if cl_header and cl_header.isdigit() and int(cl_header) > BYTE_CEILING:
                return FetchOutcome(
                    "oversize", current, content_length=int(cl_header)
                )

            ctype_header = resp.headers.get("content-type", "")
            chunks: list[bytes] = []
            total = 0
            sniffed = False
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > BYTE_CEILING:  # enforce mid-stream when length absent
                    return FetchOutcome("oversize", current, content_length=total)
                chunks.append(chunk)
                if not sniffed:
                    sniffed = True
                    kind = resolve_content_type(chunk, ctype_header, current)
                    if kind == "binary":  # short-circuit: don't download data files
                        cl = int(cl_header) if cl_header and cl_header.isdigit() else None
                        return FetchOutcome(
                            "binary_skipped", current, content_length=cl
                        )
            raw = b"".join(chunks)
            return FetchOutcome(
                "ok",
                current,
                content_type=resolve_content_type(raw, ctype_header, current),
                raw=raw,
                encoding=resp.encoding,
            )
    return FetchOutcome("fetch_error", current, error="Too many redirects.")
