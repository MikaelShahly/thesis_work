"""SQLite persistence layer.

Four tables: projects, sessions, messages, message_segments.

Conversation state is owned by the Agent SDK (per-session_id), so the
`messages` + `message_segments` tables are purely a UI mirror — never
replayed back to the LLM. `messages` anchors each turn (role +
fallback text); `message_segments` stores the ordered breakdown
(text / thinking / tool) needed to reproduce the live chat on reload.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from src.config import DB_PATH


# ── Slugify ──
# Deterministic project-name → folder-name. The JS version in
# frontend/src/lib/slugify.js must produce identical output.
_SLUG_STRIP_RE = re.compile(r"[^\w\s-]")
_SLUG_COLLAPSE_RE = re.compile(r"[\s_-]+")


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "")
    s = s.encode("ascii", "ignore").decode("ascii")
    s = _SLUG_STRIP_RE.sub("", s).strip().lower()
    s = _SLUG_COLLAPSE_RE.sub("-", s)
    return s[:60] or "project"


# ── Connection ──
@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


# ── Schema ──
_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    folder_name TEXT NOT NULL UNIQUE,
    phase TEXT NOT NULL DEFAULT 'simulation_spec',
    expertise_level TEXT NOT NULL DEFAULT 'intermediate',
    spec_draft TEXT,
    approval_pending INTEGER NOT NULL DEFAULT 0,
    approval_kind TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    sdk_session_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS message_segments (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,
    content TEXT,
    tool_use_id TEXT,
    tool_name TEXT,
    tool_input TEXT,
    tool_is_error INTEGER,
    parent_tool_use_id TEXT,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);

-- ── Observability (write-only; not replayed to the LLM, not read by the
-- chat reload path). Captures what the chat mirror omits: which model
-- ran, token usage, the system prompt + config the agent was given, and
-- the agent's own failures/retries. See docs/observability_design.md.

-- One row per AssistantMessage (one API response). Grain chosen because
-- the SDK exposes usage per-AssistantMessage. No cost column by design —
-- store raw tokens + model; a reader computes dollars if they want.
CREATE TABLE IF NOT EXISTS model_calls (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    parent_tool_use_id TEXT,
    model TEXT NOT NULL,
    stop_reason TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_creation_tokens INTEGER,
    cache_read_tokens INTEGER,
    service_tier TEXT,
    anthropic_message_id TEXT,
    error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- One row per session: the system prompt + config the agent was built
-- with (only lives in-process at build time; never in the SDK transcript).
CREATE TABLE IF NOT EXISTS session_config (
    session_id TEXT PRIMARY KEY,
    system_prompt TEXT,
    system_prompt_sha256 TEXT,
    model TEXT,
    effort TEXT,
    thinking TEXT,
    max_turns INTEGER,
    permission_mode TEXT,
    allowed_tools TEXT,
    mcp_servers TEXT,
    skills TEXT,
    cwd TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- Reliability log: the agent's own failures/retries, none of which are
-- durable today (the red error text streams to the UI but is not saved).
CREATE TABLE IF NOT EXISTS agent_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    data TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- Sub-agent narration: the intermediate text a sub-agent emits between
-- its tool calls. NOT on the live stream (the CLI doesn't forward it) and
-- NOT shown in the UI — it only exists in the sub-agent's on-disk
-- transcript, read at SubagentStop. Stored purely so the full flow can be
-- inspected later. One row per text block, ordered by `seq`.
CREATE TABLE IF NOT EXISTS subagent_narration (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    agent_id TEXT,
    agent_type TEXT,
    seq INTEGER,
    content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_segments_message ON message_segments(message_id);
CREATE INDEX IF NOT EXISTS idx_model_calls_session ON model_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_events_session ON agent_events(session_id);
CREATE INDEX IF NOT EXISTS idx_subagent_narration_session ON subagent_narration(session_id);
"""


def init_db() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)
        # Idempotent migrations for columns added after initial release.
        _ensure_column(c, "projects", "approval_pending",
                       "INTEGER NOT NULL DEFAULT 0")
        # approval_kind is the discriminator for which approval is
        # pending — "mesh_step" (request_subtask_approval),
        # "improver_experiment" (request_experiment_approval), or
        # "<phase>_phase_advance" (request_phase_advance, e.g.
        # "case_builder_phase_advance" / "mesh_phase_advance"). NULL when
        # no approval is pending. Persists across reloads so the frontend
        # restores the correct pill/panel copy and approve handler.
        _ensure_column(c, "projects", "approval_kind", "TEXT")


def _ensure_column(c, table: str, column: str, ddl: str) -> None:
    cols = [r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


class ProjectNameConflictError(Exception):
    """Raised when `create_project` would produce a duplicate folder_name."""


# ── Projects ──
def create_project(name: str, expertise_level: str = "intermediate") -> str:
    pid = str(uuid.uuid4())
    folder = slugify(name)
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO projects (id, name, expertise_level, folder_name) "
                "VALUES (?, ?, ?, ?)",
                (pid, name, expertise_level, folder),
            )
            sid = str(uuid.uuid4())
            c.execute(
                "INSERT INTO sessions (id, project_id, phase) VALUES (?, ?, ?)",
                (sid, pid, "simulation_spec"),
            )
    except sqlite3.IntegrityError as e:
        if "folder_name" in str(e):
            raise ProjectNameConflictError(folder) from e
        raise
    return pid


def get_project(project_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
    return dict(row) if row else None


def list_projects() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM projects ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_project(project_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM projects WHERE id = ?", (project_id,))


def update_project(project_id: str, **fields) -> None:
    if not fields:
        with _conn() as c:
            c.execute(
                "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (project_id,),
            )
        return
    parts = [f"{k} = ?" for k in fields]
    parts.append("updated_at = CURRENT_TIMESTAMP")
    values = list(fields.values()) + [project_id]
    with _conn() as c:
        c.execute(
            f"UPDATE projects SET {', '.join(parts)} WHERE id = ?",
            values,
        )


# ── Sessions ──
def create_session(project_id: str, phase: str) -> str:
    sid = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO sessions (id, project_id, phase) VALUES (?, ?, ?)",
            (sid, project_id, phase),
        )
    return sid


def get_current_session(project_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM sessions WHERE project_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (project_id,),
        ).fetchone()
    return dict(row) if row else None


def list_sessions(project_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM sessions WHERE project_id = ? ORDER BY created_at ASC",
            (project_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_session(session_id: str, **fields) -> None:
    if not fields:
        return
    parts = [f"{k} = ?" for k in fields]
    values = list(fields.values()) + [session_id]
    with _conn() as c:
        c.execute(
            f"UPDATE sessions SET {', '.join(parts)} WHERE id = ?",
            values,
        )


# ── Messages (UI mirror only) ──
def save_message(session_id: str, role: str, content: str) -> str:
    if not content:
        # Don't bother persisting empty assistant turns (pure tool-use, etc.).
        return ""
    mid = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO messages (id, session_id, role, content) "
            "VALUES (?, ?, ?, ?)",
            (mid, session_id, role, content),
        )
    return mid


def save_assistant_turn(
    session_id: str, text: str, segments: list[dict]
) -> str:
    """Persist an assistant turn: one `messages` row + N `message_segments`
    rows. `text` is the parent-agent prose used as a fallback when the
    frontend renders a row without segments. `segments` is the ordered
    breakdown (text / thinking / tool) the live UI displayed. Returns
    the message id (empty string when neither text nor segments are
    present — nothing was persisted).
    """
    if not text and not segments:
        return ""
    mid = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO messages (id, session_id, role, content) "
            "VALUES (?, ?, ?, ?)",
            (mid, session_id, "assistant", text or ""),
        )
        for i, s in enumerate(segments):
            is_tool = s["kind"] == "tool"
            is_err = (1 if s.get("tool_is_error") else 0) if is_tool else None
            c.execute(
                "INSERT INTO message_segments ("
                "id, message_id, seq, kind, content, tool_use_id, "
                "tool_name, tool_input, tool_is_error, parent_tool_use_id"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    mid,
                    i,
                    s["kind"],
                    s.get("content"),
                    s.get("tool_use_id"),
                    s.get("tool_name"),
                    s.get("tool_input"),
                    is_err,
                    s.get("parent_tool_use_id"),
                ),
            )
    return mid


def persist_turn(
    session_id: str,
    message_id: str | None,
    text: str,
    segments: list[dict],
) -> str:
    """Idempotent, incremental turn persist (replaces the end-of-turn
    `save_assistant_turn` batch).

    Called repeatedly during a turn — once per *completed* event (tool
    output, thinking block, sub-agent text) and once at turn end — always
    with the full current `text` + `segments`. The first call (message_id
    None) creates the assistant `messages` row; later calls update its
    `content`. Segments are written by a stable id (`<message_id>:<seq>`)
    via INSERT OR REPLACE, so re-persisting the growing list converges on
    the same rows with no duplicates. The segment list only ever grows
    within a turn, so no stale rows are left behind.

    A crash mid-turn therefore keeps every completed event already on
    disk. Returns the message id (caller threads it back in for the next
    call); empty string when there is nothing to persist.
    """
    if not text and not segments:
        return message_id or ""
    with _conn() as c:
        if message_id is None:
            message_id = str(uuid.uuid4())
            c.execute(
                "INSERT INTO messages (id, session_id, role, content) "
                "VALUES (?, ?, 'assistant', ?)",
                (message_id, session_id, text or ""),
            )
        else:
            c.execute(
                "UPDATE messages SET content = ? WHERE id = ?",
                (text or "", message_id),
            )
        for i, s in enumerate(segments):
            is_tool = s["kind"] == "tool"
            is_err = (1 if s.get("tool_is_error") else 0) if is_tool else None
            c.execute(
                "INSERT OR REPLACE INTO message_segments ("
                "id, message_id, seq, kind, content, tool_use_id, "
                "tool_name, tool_input, tool_is_error, parent_tool_use_id"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"{message_id}:{i}",
                    message_id,
                    i,
                    s["kind"],
                    s.get("content"),
                    s.get("tool_use_id"),
                    s.get("tool_name"),
                    s.get("tool_input"),
                    is_err,
                    s.get("parent_tool_use_id"),
                ),
            )
    return message_id


# ── Observability (write-only) ──
def insert_model_call(session_id: str, d: dict) -> None:
    """One row per AssistantMessage. `d` carries the fields read straight
    off the SDK object (model, usage, message_id, stop_reason,
    parent_tool_use_id, error)."""
    u = d.get("usage") or {}
    with _conn() as c:
        c.execute(
            "INSERT INTO model_calls ("
            "id, session_id, parent_tool_use_id, model, stop_reason, "
            "input_tokens, output_tokens, cache_creation_tokens, "
            "cache_read_tokens, service_tier, anthropic_message_id, error"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                session_id,
                d.get("parent_tool_use_id"),
                d.get("model") or "",
                d.get("stop_reason"),
                u.get("input_tokens"),
                u.get("output_tokens"),
                u.get("cache_creation_input_tokens"),
                u.get("cache_read_input_tokens"),
                u.get("service_tier"),
                d.get("message_id"),
                d.get("error"),
            ),
        )


def insert_session_config(session_id: str, d: dict) -> None:
    """One row per session (INSERT OR IGNORE — first writer wins)."""
    sp = d.get("system_prompt")
    sha = hashlib.sha256(sp.encode()).hexdigest() if sp else None

    def _j(v: Any) -> str | None:
        return json.dumps(v) if v is not None else None

    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO session_config ("
            "session_id, system_prompt, system_prompt_sha256, model, effort, "
            "thinking, max_turns, permission_mode, allowed_tools, mcp_servers, "
            "skills, cwd"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                sp,
                sha,
                d.get("model"),
                d.get("effort"),
                _j(d.get("thinking")),
                d.get("max_turns"),
                d.get("permission_mode"),
                _j(d.get("allowed_tools")),
                _j(d.get("mcp_servers")),
                _j(d.get("skills")),
                d.get("cwd"),
            ),
        )


def insert_agent_event(session_id: str, kind: str, data: Any) -> None:
    """Reliability/error log row. `data` is JSON-encoded unless already a
    string."""
    if data is not None and not isinstance(data, str):
        data = json.dumps(data, default=str)
    with _conn() as c:
        c.execute(
            "INSERT INTO agent_events (id, session_id, kind, data) "
            "VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), session_id, kind, data),
        )


def insert_subagent_narration(
    session_id: str,
    agent_id: str | None,
    agent_type: str | None,
    texts: list[str],
) -> None:
    """One row per sub-agent text block (ordered), read from the sub-agent's
    transcript at SubagentStop. Record-only — not shown in the UI."""
    if not texts:
        return
    with _conn() as c:
        for i, t in enumerate(texts):
            c.execute(
                "INSERT INTO subagent_narration ("
                "id, session_id, agent_id, agent_type, seq, content"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), session_id, agent_id, agent_type, i, t),
            )


def get_messages(session_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, role, content FROM messages "
            "WHERE session_id = ? ORDER BY rowid ASC",
            (session_id,),
        ).fetchall()
    return [
        {"id": r["id"], "role": r["role"], "content": r["content"]}
        for r in rows
    ]


def get_segments(message_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT kind, content, tool_use_id, tool_name, tool_input, "
            "tool_is_error, parent_tool_use_id "
            "FROM message_segments WHERE message_id = ? ORDER BY seq ASC",
            (message_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_full_chat_history(project_id: str) -> list[dict]:
    """Flat list for the frontend: message entries + phase_transition
    markers between sessions. Assistant entries include `segments` —
    the ordered text/thinking/tool breakdown — when persisted (older
    rows predate the segment table and carry only `content`).
    """
    sessions = list_sessions(project_id)
    out: list[dict] = []
    prev_phase: str | None = None
    for sess in sessions:
        if prev_phase is not None and prev_phase != sess["phase"]:
            out.append({
                "type": "phase_transition",
                "from": prev_phase,
                "to": sess["phase"],
                "timestamp": sess["created_at"],
            })
        for msg in get_messages(sess["id"]):
            if msg["role"] == "compaction":
                # Synthesized divider — content is the JSON payload from
                # the `compaction_complete` event (pre/post tokens).
                try:
                    data = json.loads(msg["content"])
                except (ValueError, TypeError):
                    data = {}
                out.append({"type": "compaction", **data})
                continue
            entry = {
                "type": "message",
                "role": msg["role"],
                "content": msg["content"],
                "phase": sess["phase"],
            }
            if msg["role"] == "assistant":
                entry["segments"] = get_segments(msg["id"])
            out.append(entry)
        prev_phase = sess["phase"]
    return out
