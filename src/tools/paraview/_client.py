"""Shared HTTP layer for the ParaView bridge tools.

Every `@tool` in `read_paraview_state.py` and `change_paraview_state.py`
calls `bridge_call("/<verb>", {...})`. This module owns:

- The bridge URL and per-call timeout.
- Error mapping: bridge unreachable, HTTP timeout, 4xx validation,
  5xx traceback — all flatten to the SDK tool-result shape with
  `is_error: True` so individual tools don't repeat that boilerplate.
- Response normalization: bridge JSON is dumped back into the tool
  result's text content (the model reads structured text, not images).

The bridge itself is a singleton on port 8765 (see
`src/paraview/lifecycle.py`); there is no per-project port.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Any


# Single project-wide bridge port. Lifecycle manager exports the same
# default; both honour `PV_BRIDGE_PORT` if set so smoke tests can swap
# in a fake server.
def _bridge_url() -> str:
    port = os.environ.get("PV_BRIDGE_PORT", "8765")
    return f"http://127.0.0.1:{port}"


# Per-call HTTP timeout. The bridge dispatches GUI work via a timer
# tick on the Qt main loop, so response time is dominated by ParaView
# work, not network. 60s covers slow filters (mesh quality on big
# meshes); the `paraview_exec` tool overrides this with its own larger
# timeout.
_DEFAULT_TIMEOUT_S = 60.0


def _ok(payload: Any) -> dict[str, Any]:
    """Wrap a successful bridge response as an SDK tool result."""
    return {
        "content": [
            {"type": "text", "text": json.dumps(payload, default=str)}
        ]
    }


def _err(message: str) -> dict[str, Any]:
    """Wrap an error as an SDK tool result with is_error set."""
    return {
        "content": [{"type": "text", "text": message}],
        "is_error": True,
    }


def _with_crash_log(message: str) -> str:
    """Append ParaView's crash output to a connection-failure message.

    When a bridge call crashes ParaView the only thing urllib reports is a
    bare disconnect/refused. ParaView's captured stderr (faulthandler
    traceback or C-level abort) is far more actionable for the agent, so
    splice it in. Lazy import to avoid a hard dependency / import cycle.
    """
    try:
        from src.paraview.lifecycle import read_paraview_log_tail

        tail = read_paraview_log_tail()
    except Exception:
        tail = None
    if not tail:
        return message
    return f"{message}\n\nParaView crash output:\n{tail}"


def _post_sync(path: str, payload: dict, timeout: float) -> dict[str, Any]:
    url = _bridge_url() + path
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return _ok(json.loads(raw))
    except urllib.error.HTTPError as e:
        # Bridge returned a non-2xx; body is JSON with {error, type, trace}
        # for 5xx, or {error: "missing 'X'"} for 4xx.
        try:
            body = json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            body = {"error": f"HTTP {e.code}"}
        msg = body.get("error") or f"HTTP {e.code}"
        if "trace" in body:
            msg = f"{msg}\n{body['trace']}"
        return _err(f"ParaView bridge error: {msg}")
    except urllib.error.URLError as e:
        # Connection refused, DNS failure, etc. The most common case
        # is "ParaView isn't open" — the agent can recover by asking
        # the user to launch it.
        return _err(_with_crash_log(
            "ParaView bridge unreachable at "
            f"{url}: {e.reason}. Is ParaView open? "
            "(Launch it yourself with `launch_paraview` if you have that "
            "tool, or ask the user to use the ParaView toolbar button.)"
        ))
    except TimeoutError:
        return _err(
            f"ParaView bridge call timed out after {timeout}s. "
            "The GUI may be busy or stuck."
        )
    except Exception as e:
        # RemoteDisconnected lands here: the call crashed ParaView mid-request.
        # Attach the captured crash output so the failure isn't opaque.
        return _err(_with_crash_log(
            f"ParaView bridge call failed: {type(e).__name__}: {e}"
        ))


async def bridge_call(
    path: str,
    payload: dict | None = None,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Invoke a bridge verb and return an SDK tool result dict."""
    return await asyncio.to_thread(_post_sync, path, payload or {}, timeout)
