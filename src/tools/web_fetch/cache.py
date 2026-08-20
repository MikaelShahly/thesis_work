"""Content-addressed per-project cache (plan §4).

Entries live under ``<cache_root>/<url_hash>/`` where ``cache_root`` is
``<project_dir>/.webcache`` (a hidden dir → excluded from the /files UI listing).
Each entry holds the staged file (``source.pdf`` | ``content.md`` | ``content.txt``),
a ``figures/`` dir, and ``meta.json`` (the full ``FetchResult``). All paths handed
back are absolute because ``cache_root`` is absolute — Read needs absolute paths.

Re-fetch within the TTL serves the stored ``meta.json`` with no network call.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from src.tools.web_fetch.schemas import FetchResult

CACHE_TTL_S = 24 * 60 * 60  # 1 day (plan §3 constants)
META_NAME = "meta.json"


def normalize_url(url: str) -> str:
    """Lower-case scheme + host, drop fragment, keep path + query.

    Query is kept because some data URLs depend on it (plan §4). Used for the
    cache key so trivially-different URLs (case, fragment) dedupe to one entry.
    """
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    return urlunsplit((scheme, netloc, parts.path, parts.query, ""))


def cache_key(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:16]


def entry_dir(cache_root: Path, url: str) -> Path:
    return cache_root / cache_key(url)


def prepare_entry(cache_root: Path, url: str) -> Path:
    """Create (or reuse) the entry dir + its ``figures/`` subdir, return the dir."""
    d = entry_dir(cache_root, url)
    (d / "figures").mkdir(parents=True, exist_ok=True)
    return d


def load_cached(
    cache_root: Path, url: str, ttl_s: int = CACHE_TTL_S
) -> FetchResult | None:
    """Return the stored ``FetchResult`` if the entry exists and is younger than
    ``ttl_s``; else ``None`` (caller fetches). Never raises."""
    meta = entry_dir(cache_root, url) / META_NAME
    try:
        if time.time() - meta.stat().st_mtime > ttl_s:
            return None
        return FetchResult.model_validate_json(meta.read_text())
    except (OSError, ValueError):
        return None


def write_meta(cache_root: Path, url: str, result: FetchResult) -> None:
    """Persist the full ``FetchResult`` as ``meta.json`` in the entry dir."""
    d = entry_dir(cache_root, url)
    d.mkdir(parents=True, exist_ok=True)
    (d / META_NAME).write_text(result.model_dump_json(exclude_none=True, indent=2))
