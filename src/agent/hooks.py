"""Hook factories for ClaudeAgentOptions.hooks.

Hooks here run **in-process** (the SDK invokes them as Python callables
when the subprocess reports a hook event). They're the bridge between
"Claude wrote a file" and "the frontend should know about it".

The file-tracking factory registers TWO PostToolUse matchers, each
with a single-purpose handler:

  - `Write|Edit` → path is in `tool_input`; resolve and emit.
  - `Bash`       → no path in `tool_input` (agent runs
    `mkdir -p Cases/baseline/system && cp …` etc); diff a project-tree
    snapshot against the prior state and emit any new or modified
    files.

Both handlers share an in-process `known: {rel_path: mtime_ns}` dict
so Bash's diff doesn't double-fire for files Write just touched.

Each handler's only side effect is enqueueing onto an asyncio.Queue,
which the caller drains between SDK message iterations in `run_turn()`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from claude_agent_sdk import HookMatcher


def _scan_project(proj_root: Path) -> dict[Path, int]:
    """Snapshot {relative_path: mtime_ns} for every file under proj_root.

    Hidden files AND files inside hidden directories (any leading-dot path
    segment) are skipped — same intent as the /files endpoint, which prunes
    dot-dirs at the top level, so the hook and the API agree on what counts.
    This keeps transient caches (the web_fetch ``.webcache/``, ParaView's
    ``.paraview_snapshots/``) from firing phantom ``file_written`` events when
    the Bash-diff tree-walk runs.
    """
    out: dict[Path, int] = {}
    if not proj_root.is_dir():
        return out
    for f in proj_root.rglob("*"):
        if not f.is_file():
            continue
        try:
            rel = f.relative_to(proj_root)
        except ValueError:
            continue
        if any(part.startswith(".") for part in rel.parts):
            continue
        try:
            out[rel] = f.stat().st_mtime_ns
        except OSError:
            continue
    return out


def _record_for(rel: Path) -> dict[str, str] | None:
    parts = rel.parts
    if not parts:
        return None
    return {
        "name": rel.name,
        "path": str(rel),
        "type": rel.suffix.lstrip(".").lower() or "",
        "subfolder": parts[0],
    }


def build_file_write_tracker(
    project_dir: Path,
    cwd: Path | None = None,
) -> tuple[asyncio.Queue[dict[str, str]], dict[str, list[HookMatcher]]]:
    """Build a PostToolUse hook that tracks Write / Edit / Bash calls.

    For Write / Edit the file path is read straight from the tool input.
    For Bash (no path in the input) we walk ``project_dir`` and diff
    against an in-process snapshot keyed by relative path → mtime_ns;
    any new or modified file fires an event. The snapshot is seeded at
    hook construction so pre-existing files (e.g. the spec written by
    /approve-spec) don't re-fire on the first Bash call.

    Writes outside the project dir are silently ignored — they don't
    belong to any UI subfolder.

    ``cwd`` defaults to ``project_dir`` (matching phases that don't
    pin cwd to a subfolder).

    Returns the queue and a hooks dict ready to merge into
    ``ClaudeAgentOptions.hooks``.
    """
    queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
    proj_root = project_dir.resolve()
    rel_root = (cwd or project_dir).resolve()

    # Seed snapshot with whatever already exists so we don't replay
    # files written in previous turns / by /approve-spec.
    known: dict[Path, int] = _scan_project(proj_root)

    async def on_write_or_edit(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict[str, Any]:
        # Write / Edit carry the file path in tool_input, so we don't
        # need a tree walk — just resolve and emit.
        tool_input = input_data.get("tool_input") or {}
        raw_path = tool_input.get("file_path")
        if not isinstance(raw_path, str) or not raw_path:
            return {}

        try:
            target = Path(raw_path)
            # Relative paths resolve against the SDK subprocess cwd
            # (the project root for case_builder). Absolute paths
            # resolve to themselves.
            if not target.is_absolute():
                target = rel_root / target
            target = target.resolve()
            rel = target.relative_to(proj_root)
        except (ValueError, OSError):
            # Outside project root, or unresolvable.
            return {}

        rec = _record_for(rel)
        if rec is None:
            return {}
        await queue.put(rec)
        try:
            known[rel] = target.stat().st_mtime_ns
        except OSError:
            pass
        return {}

    async def on_bash(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict[str, Any]:
        # Bash has no file_path in its input — the agent uses it for
        # `mkdir -p Cases/baseline/system && cp …` style folder bootstrapping,
        # which during the improver phase can touch dozens of files at
        # once (parallel run dirs, copies into iterations/). One toast
        # per file is spam, so we coalesce: count the new/modified files
        # and the distinct subfolders they land in, then emit a SINGLE
        # summary record. The files still reach the sidebar tree via the
        # frontend's silent /files refetch — this is FYI only.
        current = _scan_project(proj_root)
        count = 0
        subfolders: list[str] = []
        for rel, mtime in current.items():
            if known.get(rel) == mtime:
                continue
            if not rel.parts:
                continue
            count += 1
            sub = rel.parts[0]
            if sub not in subfolders:
                subfolders.append(sub)
        # Refresh wholesale — deletions drop out of `known` so a
        # later re-create still fires.
        known.clear()
        known.update(current)
        if count:
            await queue.put(
                {"summary": True, "count": count, "subfolders": subfolders}
            )
        return {}

    # Two matchers (rather than one regex with branching) keep each
    # handler responsible for a single tool family. This is the style
    # the SDK examples use for chained hooks.
    hooks = {
        "PostToolUse": [
            HookMatcher(matcher="Write|Edit", hooks=[on_write_or_edit]),
            HookMatcher(matcher="Bash", hooks=[on_bash]),
        ],
    }
    return queue, hooks


def merge_hooks(
    *hook_dicts: dict[str, list[HookMatcher]] | None,
) -> dict[str, list[HookMatcher]] | None:
    """Combine multiple per-event hook dicts.

    None entries are skipped. If the result is empty, returns None so
    the caller can pass it straight to ClaudeAgentOptions.hooks
    (matching the "no hooks" idiom).
    """
    merged: dict[str, list[HookMatcher]] = {}
    for d in hook_dicts:
        if not d:
            continue
        for event, matchers in d.items():
            merged.setdefault(event, []).extend(matchers)
    return merged or None
