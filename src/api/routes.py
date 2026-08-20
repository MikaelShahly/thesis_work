"""HTTP endpoints.

- POST   /projects                   create project
- GET    /projects                   list projects
- GET    /projects/{id}              project detail + full chat history
- DELETE /projects/{id}              delete project (cascades)
- POST   /projects/{id}/messages     send user message, returns SSE stream
- POST   /projects/{id}/approve-spec approve spec, transitions phase
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from src import db
from src.agent import permissions, session_registry
from src.agent.core import StreamEvent
from src.config import (
    GEOMETRY_EXTENSIONS,
    MAX_GEOMETRY_SIZE_BYTES,
    PROJECTS_DIR,
)
from src.paraview import lifecycle as paraview_lifecycle
from src.phases.case_builder import run_case_builder_turn
from src.phases.improver import run_improver_turn
from src.phases.mesh import run_mesh_turn
from src.phases.post_process import run_post_process_turn
from src.phases.simulation_spec import run_simulation_spec_turn
from src.tools.paraview._client import bridge_call as paraview_bridge_call


router = APIRouter()


# ── Phase dispatch ─────────────────────────────────────────────────────
PHASE_HANDLERS = {
    "simulation_spec": run_simulation_spec_turn,
    "case_builder": run_case_builder_turn,
    "mesh": run_mesh_turn,
    "improver": run_improver_turn,
    "post_process": run_post_process_turn,
}

# Prefixes the frontend prepends to a feedback turn. Receiving a
# message starting with one of these clears `approval_pending` so
# the UI exits the pending pill state on reload.
# - `_MESH_FEEDBACK_PREFIX`: mesh sub-step feedback. Covers both
#   `request_subtask_approval` (mesh phase) and `request_mesh_approval`
#   (improver phase) — they share the same approval wiring.
# - `_EXPERIMENT_FEEDBACK_PREFIX`: improver experiment-plan feedback
#   (request_experiment_approval).
# - `_PHASE_ADVANCE_FEEDBACK_PREFIX`: phase-advance feedback for any
#   phase. request_phase_advance is the phase-completion gate for every
#   phase (case_builder, mesh, improver), so its feedback prefix is
#   phase-agnostic — the on-wire prefix doesn't name the phase (the
#   agent reads context).
_MESH_FEEDBACK_PREFIX = "[Feedback on mesh]:"
_EXPERIMENT_FEEDBACK_PREFIX = "[Feedback on experiment]:"
_PHASE_ADVANCE_FEEDBACK_PREFIX = "[Feedback]:"

# Backend-owned kickoff prompt for the case_builder agent's first turn,
# fired automatically when /approve-spec transitions the phase. Not
# persisted as a user message — the user did not write it.
_CASE_BUILDER_KICKOFF = (
    "Begin building the case from the approved specification."
)

# Backend-owned kickoff for the mesh agent's resumed turn after the
# user approves a sub-step. Auto-resume keeps the user out of the
# loop of typing "continue" between every sub-step.
_MESH_SUBTASK_KICKOFF = "User approved the mesh sub-step. Proceed."

# Backend-owned kickoff for the improver agent's resumed turn after
# the user approves an experiment plan. Same auto-resume pattern as
# the mesh sub-step kickoff.
_IMPROVER_EXPERIMENT_KICKOFF = "User approved the experiment plan. Proceed."

# Backend-owned kickoff for the mesh agent's first turn after the
# case_builder phase advances. Mirrors `_CASE_BUILDER_KICKOFF`
# for the spec → case_builder transition.
_MESH_KICKOFF = (
    "Begin building the mesh. The approved spec is in Specification/, "
    "the case in Case/, and the case_builder's handoff in "
    "handoffs/case_builder.md."
)
# Kickoff for the improver agent's first turn after the mesh phase
# advances. The system prompt embeds the full context (approved spec,
# project structure, handoff paths) so the kickoff itself can stay
# terse.
_IMPROVER_KICKOFF = "Proceed with your task."

# Kickoff for the post_process agent's first turn after the improver
# phase advances. The system prompt carries the full
# context (where to read the spec/case/handoff, the two-stage workflow)
# so the kickoff stays terse — the agent reads the case, then agrees the
# deliverable with the user via AskUserQuestion.
_POST_PROCESS_KICKOFF = "Proceed with your task."

# SSE event type → approval kind discriminator. Persisted to
# `projects.approval_kind` so a page reload restores the correct
# pill / panel copy and approve handler.
#
# Membership matters: code uses `ev.type in _APPROVAL_KINDS` to
# decide whether an event represents a user-facing approval (and
# should flip `approval_pending`). Phase-advance is intentionally
# present here with `None` to mark it as approval-bearing — the
# actual discriminator value is phase-aware and computed by
# `_approval_kind_for()` at the call site.
_APPROVAL_KINDS = {
    "subtask_approval_requested": "mesh_step",
    "experiment_approval_requested": "improver_experiment",
    "phase_advance_requested": None,
}


def _approval_kind_for(event_type: str, phase: str) -> str | None:
    """Resolve the persisted `approval_kind` for an approval event.

    `phase_advance_requested` is phase-aware — the same
    `request_phase_advance` tool is the phase-completion gate for every
    agent, and the UI distinguishes the resulting pill / feedback panel
    copy via a phase-specific discriminator (`case_builder_phase_advance`,
    `mesh_phase_advance`, `improver_phase_advance`). Other approval events
    are flat — the tool itself is phase-specific.
    """
    if event_type == "phase_advance_requested":
        return f"{phase}_phase_advance"
    return _APPROVAL_KINDS.get(event_type)

PHASE_DISPLAY = {
    "simulation_spec": "Spec",
    "case_builder": "Case",
    "mesh": "Meshing",
    "improver": "Running",
    "post_process": "Post",
}

# Subfolders materialised under projects/{folder_name}/ at project creation.
# The sidebar tree always shows these; files appear inside them as the
# agent (or approve-spec) writes. `Geometry/` is the destination for
# user-uploaded mesh/CAD files (phase 3); the mesh/case-builder agents
# read from there. `Cases/` is the parent for OpenFOAM cases — the
# agent creates one named subfolder per case (e.g. Cases/baseline/).
PROJECT_SUBFOLDERS = (
    "Specification", "Geometry", "Cases", "handoffs",
)


# ── Request/response models ────────────────────────────────────────────
class CreateProjectBody(BaseModel):
    name: str = Field(min_length=1)
    expertise_level: str = Field(default="intermediate")


class SendMessageBody(BaseModel):
    content: str = Field(min_length=1)


class PermissionDecisionBody(BaseModel):
    decision: str = Field(pattern="^(allow|deny)$")


class PermissionDenyFeedbackBody(BaseModel):
    message: str = Field(min_length=1)


class QuestionAnswerBody(BaseModel):
    # `questions` is echoed straight back (the SDK needs it to process
    # the tool); `answers` maps question text → label / list of labels /
    # free text. `response` is an optional freeform reply.
    questions: list
    answers: dict
    response: str | None = None


class ParaviewLaunchBody(BaseModel):
    foam_file: str | None = Field(default=None)


class ParaviewLoadBody(BaseModel):
    foam_file: str = Field(min_length=1)


# ── Helpers ────────────────────────────────────────────────────────────
def _project_summary(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "folder_name": row.get("folder_name"),
        "phase": row["phase"],
        "phase_display": PHASE_DISPLAY.get(row["phase"], row["phase"]),
        "expertise_level": row["expertise_level"],
        "status": row["status"],
        "approval_pending": bool(row.get("approval_pending") or 0),
        "approval_kind": row.get("approval_kind"),
        # True iff a turn is actively running (drives the red interrupt
        # icon + composer gating + re-attach on switch-back). A running
        # *background task* does NOT make this true.
        "turn_active": _turn_active_for(row["id"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _project_dir(row: dict) -> Path:
    return PROJECTS_DIR / row["folder_name"]


def _sse_payload(event: StreamEvent) -> dict:
    return {"event": event.type, "data": json.dumps(event.data)}


# Events the API consumes itself; never forwarded to the client.
_INTERNAL_EVENTS = {
    "sdk_session_id", "assistant_turn",
    "turn_persist", "model_call", "session_config", "agent_event",
    "subagent_narration",
}

# project_id -> the in-progress assistant message id for the current turn.
# Threaded through `persist_turn` so each incremental checkpoint upserts the
# same `messages` row (and its segments) instead of inserting duplicates.
# Cleared at the turn boundary (`turn_complete`).
_turn_message: dict[str, str] = {}


def _persist_compaction(project_id: str, ev: StreamEvent) -> None:
    """Persist a `compaction_complete` event as a `compaction` message
    row so the chat divider survives reload.

    `get_current_session` resolves to whichever session is streaming at
    the moment compaction fired — correct even in the handoff endpoints
    that flip the phase (and create a new session) mid-stream, since the
    boundary always lands inside the turn that triggered it.
    """
    sess = db.get_current_session(project_id)
    if sess:
        db.save_message(sess["id"], "compaction", json.dumps(ev.data))


# ── Turn buffering (disconnect-survival + re-attach) ────────────────────
# A turn is driven by a detached task and its SSE payloads are buffered
# per project. This decouples the turn (and its DB persistence) from any
# single HTTP connection: the task runs to completion even if the client
# disconnects (project switch), and a re-attaching client replays what it
# missed then follows live. See GET /projects/{id}/stream.
class _TurnBuffer:
    def __init__(self) -> None:
        self._log: list[dict] = []          # replayable events (all subscribers)
        self._subs: set[asyncio.Queue] = set()
        self._pending_live: list[dict] = []  # live-only events awaiting 1st subscriber
        self._had_subscriber = False
        self._done = False

    def push(self, payload: dict, replay: bool = True) -> None:
        if replay:
            self._log.append(payload)
            for q in self._subs:
                q.put_nowait(payload)
            return
        # Live-only (one-shot transition marker, e.g. spec_approved): deliver
        # to current subscribers; if none has attached yet, hold it for the
        # *first* subscriber so the subscribe-vs-push race can't drop it. Never
        # added to the replay log, so re-attaching clients don't replay it —
        # they get the new phase + divider from their history reload instead.
        if self._subs:
            for q in self._subs:
                q.put_nowait(payload)
        elif not self._had_subscriber:
            self._pending_live.append(payload)

    def reset(self) -> None:
        # Clear the replay log at a turn boundary in a multi-turn sequence
        # (handoff -> kickoff). The completed turn is already persisted to
        # the DB (history), so a re-attaching client must replay only the
        # *current* turn — not the finished one (which would duplicate it and
        # replay a stale turn_complete). Does not touch current subscribers,
        # who have already received the prior turn live.
        self._log.clear()
        self._pending_live.clear()

    def close(self) -> None:
        self._done = True
        for q in self._subs:
            q.put_nowait(None)

    async def stream(self) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue()
        first = not self._had_subscriber
        self._had_subscriber = True
        self._subs.add(q)
        # Snapshot synchronously (no await) so a concurrent push can't land in
        # both the backlog and the live queue (which would double it).
        pending = self._pending_live if first else []
        if first:
            self._pending_live = []
        backlog = list(self._log)
        try:
            for payload in pending:    # live-only events held for the first client
                yield payload
            for payload in backlog:    # replayable backlog
                yield payload
            if self._done:
                return
            while True:
                payload = await q.get()
                if payload is None:    # close sentinel
                    return
                yield payload
        finally:
            self._subs.discard(q)


# project_id -> active turn buffer (present iff a turn is streaming)
_active_turns: dict[str, _TurnBuffer] = {}


def _turn_active_for(project_id: str) -> bool:
    """Is a turn actively running for this project? (Not a background task.)"""
    if project_id in _active_turns:
        return True
    w = session_registry.get_by_project(project_id)
    return bool(w is not None and w.turn_active)


def _record_in_turn_buffer(project_id: str, event_type: str, data: dict) -> None:
    """Record an out-of-band turn event into the active buffer.

    Interactive prompts (permission / AskUserQuestion) are resolved on
    their own HTTP endpoints, *not* through the turn's event stream. Without
    this, a client that re-attaches mid-turn replays the buffered
    `*_requested` event with no matching `*_resolved`, so the panel re-pops.
    Recording the resolution keeps re-attach consistent (request → resolved
    → panel closed).
    """
    buf = _active_turns.get(project_id)
    if buf is not None:
        buf.push(_sse_payload(StreamEvent(event_type, data)))


def _start_turn_buffer(project_id: str, drive_fn) -> _TurnBuffer:
    """Run a turn (or turn sequence) in a detached, buffered task.

    Decouples the turn from any HTTP connection: `drive_fn(buffer)` runs in a
    background task that survives the client disconnecting, owns all DB
    side-effects, and emits SSE payloads via `buffer.push(payload)` (and
    `buffer.reset()` at a turn boundary in a multi-turn sequence). The buffer
    is registered in `_active_turns` so any GET /stream re-attach tails it.

    Shared by the HTTP turn entrypoints (via `stream_buffered`) and by
    autonomous turns the worker starts itself (which have no HTTP response).
    """
    buffer = _TurnBuffer()
    _active_turns[project_id] = buffer

    async def runner() -> None:
        try:
            await drive_fn(buffer)
        except Exception as e:
            data = {"message": f"{type(e).__name__}: {e}", "recoverable": False}
            buffer.push(_sse_payload(StreamEvent("error", data)))
            # This crash bypasses the per-event side-effect path, so persist
            # it here too — otherwise a drive-task failure leaves no record.
            try:
                sess = db.get_current_session(project_id)
                if sess:
                    db.insert_agent_event(sess["id"], "app_error", data)
            except Exception:
                pass
        finally:
            _turn_message.pop(project_id, None)
            _active_turns.pop(project_id, None)
            buffer.close()

    asyncio.create_task(runner())
    return buffer


def stream_buffered(project_id: str, drive_fn) -> EventSourceResponse:
    """HTTP entrypoint: start the buffered turn and tail it over SSE."""
    buffer = _start_turn_buffer(project_id, drive_fn)
    return EventSourceResponse(buffer.stream())


async def _drive_autonomous_turn(worker, queue) -> None:
    """Buffer + persist a turn the worker started on its own (a
    background-task / Monitor wake-up re-invoked the agent — no POST drove
    it). Mirrors send_message's drive minus the user message + HTTP response:
    the buffer lives in `_active_turns`, so a viewing client picks it up via
    GET /stream (the frontend polls `turn_active` and re-attaches).

    `queue` is the worker's fresh turn queue, captured at turn start and
    passed through so a fast turn boundary can't strand its events.
    """
    project_id = worker.project_id
    if project_id is None or project_id in _active_turns:
        return
    project = db.get_project(project_id)
    session = db.get_current_session(project_id)
    if project is None or session is None:
        return

    async def drive(buffer) -> None:
        try:
            async for ev in worker.consume_turn(queue):
                if _apply_turn_side_effect(project_id, session, project, ev):
                    buffer.push(_sse_payload(ev))
        finally:
            db.update_project(project_id)

    _start_turn_buffer(project_id, drive)


# Wire the worker → route autonomous-turn driver (avoids an import cycle:
# the registry is imported by the worker; routes imports the registry).
session_registry.set_autonomous_turn_handler(_drive_autonomous_turn)


def _apply_turn_side_effect(
    project_id: str, session: dict, project: dict, ev: StreamEvent
) -> bool:
    """Apply a streamed event's DB side-effects. Returns True if the event
    should be forwarded to clients (False = internal-only).

    Runs in the detached drive task, so persistence happens regardless of
    whether any client is connected.
    """
    if ev.type == "sdk_session_id":
        db.update_session(session["id"], sdk_session_id=ev.data["session_id"])
        return False
    # Incremental turn persistence: both the mid-turn checkpoints
    # (`turn_persist`) and the final end-of-turn snapshot (`assistant_turn`)
    # upsert the same message row via the threaded message id.
    if ev.type in ("turn_persist", "assistant_turn"):
        mid = db.persist_turn(
            session["id"],
            _turn_message.get(project_id),
            ev.data.get("text", ""),
            ev.data.get("segments", []),
        )
        if mid:
            _turn_message[project_id] = mid
        return False
    if ev.type == "model_call":
        db.insert_model_call(session["id"], ev.data)
        return False
    if ev.type == "session_config":
        db.insert_session_config(session["id"], ev.data)
        return False
    if ev.type == "agent_event":
        db.insert_agent_event(
            session["id"], ev.data.get("kind", "unknown"), ev.data.get("data"),
        )
        return False
    if ev.type == "subagent_narration":
        db.insert_subagent_narration(
            session["id"],
            ev.data.get("agent_id"),
            ev.data.get("agent_type"),
            ev.data.get("texts", []),
        )
        return False
    if ev.type == "turn_complete":
        # Turn boundary: the next turn must open a fresh message row.
        _turn_message.pop(project_id, None)
    if ev.type == "error":
        # The red error text in the UI — durable now (forwarded too).
        db.insert_agent_event(session["id"], "app_error", ev.data)
    if ev.type == "specification_presented":
        db.update_project(project_id, spec_draft=ev.data.get("markdown", ""))
    if ev.type in _APPROVAL_KINDS:
        db.update_project(
            project_id,
            approval_pending=1,
            approval_kind=_approval_kind_for(ev.type, project["phase"]),
        )
    if ev.type == "compaction_complete":
        _persist_compaction(project_id, ev)
    if ev.type in _INTERNAL_EVENTS:
        return False
    return True


# ── Project CRUD ───────────────────────────────────────────────────────
@router.post("/projects")
def create_project(body: CreateProjectBody) -> dict:
    try:
        pid = db.create_project(body.name, body.expertise_level)
    except db.ProjectNameConflictError:
        raise HTTPException(
            status_code=409,
            detail="A project with that name already exists.",
        )
    row = db.get_project(pid)
    proj_dir = _project_dir(row)
    proj_dir.mkdir(parents=True, exist_ok=True)
    for sub in PROJECT_SUBFOLDERS:
        (proj_dir / sub).mkdir(exist_ok=True)
    return _project_summary(row)


@router.get("/projects")
def list_projects() -> list[dict]:
    return [_project_summary(p) for p in db.list_projects()]


@router.get("/projects/{project_id}")
def get_project(project_id: str) -> dict:
    row = db.get_project(project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        **_project_summary(row),
        "spec_draft": row["spec_draft"],
        "history": db.get_full_chat_history(project_id),
    }


@router.get("/projects/{project_id}/files")
def list_project_files(project_id: str) -> dict:
    project = db.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    proj_dir = _project_dir(project)

    # Discover every top-level directory under the project root. The
    # blessed PROJECT_SUBFOLDERS still get pre-created at project
    # creation so they always appear in a stable order; this scan
    # additionally surfaces any folder the agent (or user) created
    # afterwards — temporary log dirs, scratch artefacts, anything.
    # The render-order convention (blessed first, then alphabetical
    # for the rest) is the frontend's responsibility; here we just
    # return the keys we found.
    tree: dict[str, list[dict]] = {}
    # Seed blessed folders so they appear in the response even when
    # empty — the frontend depends on this for the stable layout.
    for sub in PROJECT_SUBFOLDERS:
        tree[sub] = []

    if proj_dir.is_dir():
        for entry in sorted(proj_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            tree.setdefault(entry.name, [])
            for f in sorted(entry.rglob("*")):
                if not f.is_file() or f.name.startswith("."):
                    continue
                rel = f.relative_to(proj_dir)
                tree[entry.name].append({
                    "name": f.name,
                    "path": str(rel),
                    "type": f.suffix.lstrip(".").lower() or "",
                })

    return tree


@router.get("/projects/{project_id}/file")
def read_project_file(project_id: str, path: str, offset: int = 0) -> dict:
    project = db.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    proj_dir = _project_dir(project).resolve()
    target = (proj_dir / path).resolve()

    # Path containment — defends against ../ traversal.
    try:
        target.relative_to(proj_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path outside project")

    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    size = target.stat().st_size
    # Tail support: the FilePanel re-requests with `offset` set to the
    # bytes it already has, so a growing log (a running solver/mesh job)
    # streams in as deltas. If the file shrank below `offset` it was
    # rotated/overwritten (e.g. the agent re-ran with the same log name)
    # — flag it so the client resets and we resend from the top.
    truncated = offset > size
    read_from = 0 if (truncated or offset < 0) else offset
    try:
        with target.open("rb") as f:
            f.seek(read_from)
            raw = f.read()
        # At offset 0 decode strictly so a genuinely binary file (binary
        # STL, .step, a binary OpenFOAM field) trips UnicodeDecodeError
        # and renders the "binary file" placeholder. A tail read (offset
        # > 0) is on a file already confirmed text, so tolerate a UTF-8
        # char split across the offset boundary rather than mis-flag it.
        content = raw.decode("utf-8") if read_from == 0 else raw.decode("utf-8", errors="replace")
        is_binary = False
    except UnicodeDecodeError:
        content = None
        is_binary = True

    return {
        "name": target.name,
        "path": path,
        "type": target.suffix.lstrip(".").lower() or "",
        "size": size,
        "is_binary": is_binary,
        "content": content,
        "offset": read_from,
        "truncated": truncated,
    }


@router.get("/projects/{project_id}/file/raw")
def read_project_file_raw(project_id: str, path: str) -> FileResponse:
    """Serve a file's raw bytes with a guessed content-type.

    Binary deliverables — figures today, PDF/HTML reports later — can't
    ride the JSON `/file` endpoint, so the frontend points an `<img>`
    (or future `<iframe>`) at this URL instead. Same `../` containment
    guard as `read_project_file`.
    """
    project = db.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    proj_dir = _project_dir(project).resolve()
    target = (proj_dir / path).resolve()

    # Path containment — defends against ../ traversal.
    try:
        target.relative_to(proj_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path outside project")

    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # mimetypes mislabels .svg on some systems; pin it so the browser
    # renders the image instead of showing raw XML.
    if target.suffix.lower() == ".svg":
        media_type = "image/svg+xml"
    else:
        media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(target, media_type=media_type)


# ── Geometry upload ────────────────────────────────────────────────────
def _sanitise_geometry_filename(raw: str) -> str:
    """Strip directory components, leading dots, and odd whitespace.

    The frontend's `<input type=file>` already gives us a filename with
    no directory parts on most browsers, but we don't trust that —
    `Path(raw).name` is the load-bearing defence against `../escape`.
    Leading dots (`.bashrc`-style) are stripped so an upload can't
    create a hidden file inside `Geometry/`.
    """
    base = Path(raw).name.strip()
    base = base.lstrip(".")
    if not base:
        raise HTTPException(status_code=400, detail="Empty filename")
    return base


def _resolve_collision(geom_dir: Path, name: str) -> Path:
    """Return an unused path inside `geom_dir` for `name`.

    On collision, append `_1`, `_2`, … to the stem (preserving the
    extension). Stops at 1000 to avoid pathological loops.
    """
    target = geom_dir / name
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    for i in range(1, 1001):
        candidate = geom_dir / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
    raise HTTPException(
        status_code=409,
        detail=f"Too many collisions for filename {name!r}",
    )


_UPLOAD_CHUNK = 1024 * 1024  # 1 MiB


@router.post("/projects/{project_id}/geometry")
async def upload_geometry(project_id: str, file: UploadFile = File(...)) -> dict:
    """Accept a geometry file and write it to `<project>/Geometry/`.

    Validates the extension against the allowlist (415 on rejection),
    sanitises the filename, resolves collisions with `_1`, `_2`, …,
    and stream-writes in 1 MiB chunks while enforcing the size cap.
    On any failure mid-write the partial file is unlinked so the
    project tree stays consistent.
    """
    project = db.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename in upload")

    sanitised = _sanitise_geometry_filename(file.filename)
    ext = Path(sanitised).suffix.lower()
    if ext not in GEOMETRY_EXTENSIONS:
        allowed = ", ".join(sorted(GEOMETRY_EXTENSIONS))
        raise HTTPException(
            status_code=415,
            detail=f"Extension {ext!r} not accepted. Allowed: {allowed}",
        )

    geom_dir = _project_dir(project) / "Geometry"
    geom_dir.mkdir(parents=True, exist_ok=True)
    target = _resolve_collision(geom_dir, sanitised)

    written = 0
    try:
        with open(target, "wb") as out:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_GEOMETRY_SIZE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"Upload exceeds {MAX_GEOMETRY_SIZE_BYTES} bytes "
                            "(see MAX_GEOMETRY_SIZE_BYTES in src/config.py)."
                        ),
                    )
                out.write(chunk)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    rel_path = target.relative_to(_project_dir(project))
    db.update_project(project_id)
    return {
        "name": target.name,
        "path": str(rel_path),
        "type": target.suffix.lstrip(".").lower() or "",
        "size": written,
        "subfolder": "Geometry",
    }


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str) -> dict:
    row = db.get_project(project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    # If the live ParaView bridge is bound to this project, it now points at
    # files we're about to remove. We don't kill it out from under the user —
    # we report the attachment so the frontend can ask them to close it.
    live = paraview_lifecycle.current_project()
    paraview_attached = live is not None and live[0] == project_id
    # Tear down any live worker for this project (kills its subprocess +
    # background jobs) before removing the files.
    await session_registry.close_project(project_id)
    proj_dir = _project_dir(row)
    if proj_dir.exists():
        shutil.rmtree(proj_dir, ignore_errors=True)
    db.delete_project(project_id)
    return {
        "status": "deleted",
        "id": project_id,
        "paraview_attached": paraview_attached,
    }


# ── Messages (SSE) ─────────────────────────────────────────────────────
@router.post("/projects/{project_id}/messages")
async def send_message(project_id: str, body: SendMessageBody):
    project = db.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    handler = PHASE_HANDLERS.get(project["phase"])
    if handler is None:
        raise HTTPException(
            status_code=400,
            detail=f"Phase {project['phase']!r} is not yet implemented",
        )

    # One turn at a time per project (persistent worker can't run two
    # turns on one client). The frontend gates this too, but enforce it
    # server-side so a sneak-through can't corrupt the stream. To watch a
    # turn that's already running (e.g. after switching back), the client
    # uses GET /projects/{id}/stream rather than POSTing again.
    existing = session_registry.get_by_project(project_id)
    if project_id in _active_turns or (existing is not None and existing.turn_active):
        raise HTTPException(
            status_code=409,
            detail="A turn is already running for this project.",
        )

    session = db.get_current_session(project_id)
    if session is None:
        sid = db.create_session(project_id, project["phase"])
        session = {"id": sid, "phase": project["phase"], "sdk_session_id": None}

    # Persist the user's turn before streaming. A dropped connection
    # mid-stream still leaves the input on disk.
    db.save_message(session["id"], "user", body.content)

    # Feedback turn during an approval-pending phase clears the
    # approval-pending flag — the user has rejected the current
    # artifact, so the UI shouldn't default back into approval state
    # on reload. Sub-step approvals use a phase/scope-specific
    # prefix; phase-advance feedback uses the phase-agnostic
    # [Feedback]: prefix regardless of which phase raised the
    # approval.
    stripped = body.content.lstrip()
    # Mesh feedback prefix covers both phases — `request_mesh_approval`
    # (improver) reuses the mesh wiring, so feedback on it arrives with
    # the same prefix.
    is_mesh_feedback = (
        project["phase"] in ("mesh", "improver")
        and stripped.startswith(_MESH_FEEDBACK_PREFIX)
    )
    is_experiment_feedback = (
        project["phase"] == "improver"
        and stripped.startswith(_EXPERIMENT_FEEDBACK_PREFIX)
    )
    # Phase-advance feedback is phase-agnostic: case_builder, mesh, and
    # improver all gate on `request_phase_advance` with this prefix.
    is_phase_advance_feedback = stripped.startswith(
        _PHASE_ADVANCE_FEEDBACK_PREFIX
    )
    if (
        is_mesh_feedback
        or is_experiment_feedback
        or is_phase_advance_feedback
    ):
        db.update_project(project_id, approval_pending=0, approval_kind=None)
    else:
        db.update_project(project_id)

    # Drive the turn in a DETACHED task so it (and its DB persistence)
    # survives the client disconnecting (e.g. project switch). The task
    # pushes SSE payloads into a per-project buffer; this response — and
    # any later GET /stream re-attach — just tails that buffer.
    async def drive(buffer) -> None:
        push = buffer.push
        try:
            async for ev in handler(
                user_message=body.content,
                expertise_level=project["expertise_level"],
                resume_session_id=session.get("sdk_session_id"),
                project_dir=_project_dir(project),
                project_id=project_id,
            ):
                if _apply_turn_side_effect(project_id, session, project, ev):
                    push(_sse_payload(ev))
        finally:
            db.update_project(project_id)

    return stream_buffered(project_id, drive)


@router.get("/projects/{project_id}/stream")
async def stream_active_turn(project_id: str):
    """Re-attach to a turn that's already running (e.g. after switching
    back to this project). Replays what was emitted so far, then follows
    live until the turn completes. If no turn is active, the stream closes
    immediately.
    """
    if db.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    buffer = _active_turns.get(project_id)
    if buffer is None:
        async def _empty() -> AsyncIterator[dict]:
            if False:
                yield {}  # pragma: no cover — empty async generator
        return EventSourceResponse(_empty())
    return EventSourceResponse(buffer.stream())


@router.get("/projects/{project_id}/turn-active")
async def turn_active_status(project_id: str) -> dict:
    """Lightweight poll target: is a turn running for this project right now?

    The frontend polls this while viewing a project so it can re-attach to a
    turn the worker started on its own (background-task / Monitor wake-up) —
    the browser, unlike the TUI, has no open connection between turns.
    """
    return {"turn_active": _turn_active_for(project_id)}


# ── Spec approval ──────────────────────────────────────────────────────
@router.post("/projects/{project_id}/approve-spec")
async def approve_spec(project_id: str):
    """Approve the spec draft and stream the case_builder kickoff turn.

    Returns SSE: a `spec_approved` event up front (so the UI can flip
    the phase pill / badge / divider immediately), followed by the
    full case_builder turn driven by a backend-owned kickoff prompt.
    The kickoff prompt is NOT persisted to the messages table — the
    user did not write it.
    """
    project = db.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    draft = project["spec_draft"]
    if not draft:
        raise HTTPException(
            status_code=400,
            detail="No specification draft available to approve",
        )
    if project["phase"] != "simulation_spec":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve spec from phase {project['phase']!r}",
        )

    proj_dir = _project_dir(project)
    spec_dir = proj_dir / "Specification"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "simulation_specification.md").write_text(draft)

    case_session_id = db.create_session(project_id, "case_builder")
    db.update_project(project_id, phase="case_builder")

    approval_payload = {
        "status": "approved",
        "phase_from": "simulation_spec",
        "phase_to": "case_builder",
        "transitioned_at": datetime.now(timezone.utc).isoformat(),
    }

    # Persistence + phase context for the kickoff turn use the new
    # case_builder session (created above), and the post-transition phase.
    case_session = {"id": case_session_id, "phase": "case_builder", "sdk_session_id": None}
    project_cb = {**project, "phase": "case_builder"}

    async def drive(buffer) -> None:
        push = buffer.push
        # Surface the transition first so a *live* client renders the badge /
        # divider / phase pill. Live-only: a re-attaching client gets the new
        # phase + the synthesized divider from its history reload, so we must
        # not replay this (it would duplicate the divider).
        push(_sse_payload(StreamEvent("spec_approved", approval_payload)), replay=False)
        try:
            async for ev in run_case_builder_turn(
                user_message=_CASE_BUILDER_KICKOFF,
                expertise_level=project["expertise_level"],
                # Fresh case_builder session — no SDK state to resume.
                resume_session_id=None,
                project_dir=proj_dir,
                project_id=project_id,
            ):
                if _apply_turn_side_effect(project_id, case_session, project_cb, ev):
                    push(_sse_payload(ev))
        finally:
            db.update_project(project_id)

    return stream_buffered(project_id, drive)


# ── Phase advance (single gate for every phase) ────────────────────────
# request_phase_advance is the phase-completion gate for case_builder,
# mesh, and improver. Each row says where the phase goes and which
# kickoff to fire on the downstream session; the downstream agent's turn
# handler is resolved from PHASE_HANDLERS[phase_to]. The handoff doc +
# updated spec are already on disk (the agent wrote them BEFORE calling
# the tool), so the route advances directly — no handoff turn, no commit.
_PHASE_ADVANCE = {
    "case_builder": {"to": "mesh",         "kickoff": _MESH_KICKOFF},
    "mesh":         {"to": "improver",     "kickoff": _IMPROVER_KICKOFF},
    "improver":     {"to": "post_process", "kickoff": _POST_PROCESS_KICKOFF},
}


@router.post("/projects/{project_id}/approve-phase-advance")
async def approve_phase_advance(project_id: str):
    """Approve the current phase and advance to the next one.

    The single approval endpoint for every `request_phase_advance` gate
    (case_builder → mesh → improver → post_process). Because the agent
    already wrote `handoffs/<phase>.md` and updated the spec before
    calling the tool, this route advances directly:
      1. `phase_approved` up front (UI clears the pill).
      2. Flips `projects.phase`, opens the downstream session, emits
         `phase_transitioned` (live-only — the divider comes from the
         re-attacher's history reload via the new session boundary).
      3. Fires the downstream agent's kickoff turn on the SAME SSE stream.
    """
    project = db.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    transition = _PHASE_ADVANCE.get(project["phase"])
    if transition is None:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot advance phase from phase {project['phase']!r}",
        )

    session = db.get_current_session(project_id)
    if session is None:
        raise HTTPException(
            status_code=500,
            detail=f"No active session found for the {project['phase']} phase",
        )

    phase_from = project["phase"]
    phase_to = transition["to"]
    proj_dir = _project_dir(project)
    approval_payload = {
        "status": "approved",
        "phase_from": phase_from,
        "phase_to": phase_to,
    }

    async def drive(buffer) -> None:
        push = buffer.push
        # phase_approved only clears the pill (no divider), so it's
        # replayable — a client re-attaching before the kickoff streams
        # replays it to clear the pill.
        push(_sse_payload(StreamEvent("phase_approved", approval_payload)))

        try:
            downstream_session_id = db.create_session(project_id, phase_to)
            db.update_project(
                project_id, phase=phase_to,
                approval_pending=0, approval_kind=None,
            )
            transitioned = {
                "phase_from": phase_from,
                "phase_to": phase_to,
                "transitioned_at": datetime.now(timezone.utc).isoformat(),
                # Same buffer is about to carry the downstream kickoff —
                # keep the UI in "agent running" mode across the divider.
                "downstream_agent_starting": True,
            }
            # Live-only: a re-attacher gets the divider from its history
            # reload (the new downstream session boundary), so replaying
            # would duplicate it.
            push(_sse_payload(StreamEvent("phase_transitioned", transitioned)), replay=False)

            # ── Downstream kickoff turn (fresh session) ──
            downstream_session = {
                "id": downstream_session_id, "phase": phase_to, "sdk_session_id": None,
            }
            project_downstream = {**project, "phase": phase_to}
            async for ev in PHASE_HANDLERS[phase_to](
                user_message=transition["kickoff"],
                expertise_level=project["expertise_level"],
                resume_session_id=None,
                project_dir=proj_dir,
                project_id=project_id,
            ):
                if _apply_turn_side_effect(
                    project_id, downstream_session, project_downstream, ev
                ):
                    push(_sse_payload(ev))
        finally:
            db.update_project(project_id)

    return stream_buffered(project_id, drive)


# ── Mesh sub-step approval (auto-resumes the agent on approve) ─────────
@router.post("/projects/{project_id}/approve-mesh-step")
async def approve_mesh_step(project_id: str):
    """Approve a mesh sub-step and stream the auto-resumed agent turn.

    Returns SSE: a `mesh_step_approved` event up front (so the UI can
    clear the pill / panel immediately), followed by the resumed agent
    turn driven by a backend-owned "Proceed" prompt. The kickoff prompt
    is NOT persisted as a user message — the user did not write it.
    Unlike /approve-phase-advance, this does NOT advance the phase: the
    agent has more sub-steps to do.

    Handles two callers:
    - Mesh phase: `request_subtask_approval` (per-sub-step approval).
    - Improver phase: `request_mesh_approval` (mesh approval mid-
      experiment, before launching the solver). The improver reuses the
      mesh-step wiring — same event, same approval_kind, same prefix.
    """
    project = db.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project["phase"] not in ("mesh", "improver"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot approve mesh sub-step from phase "
                f"{project['phase']!r}"
            ),
        )

    session = db.get_current_session(project_id)
    if session is None:
        raise HTTPException(
            status_code=500,
            detail=(
                f"No active session found for the {project['phase']} phase"
            ),
        )

    db.update_project(
        project_id, approval_pending=0, approval_kind=None,
    )

    proj_dir = _project_dir(project)
    # Dispatch to the right phase handler. Both share the same kickoff
    # text — "User approved the mesh sub-step. Proceed." — which is
    # fine for the improver too: it just means "resume your loop".
    phase_handler = (
        run_mesh_turn if project["phase"] == "mesh" else run_improver_turn
    )

    async def drive(buffer) -> None:
        push = buffer.push
        # Surface the approval first so the UI can clear the AcceptPanel
        # / pill before the agent starts streaming.
        push(_sse_payload(StreamEvent("mesh_step_approved", {
            "status": "approved",
            "auto_resumed": True,
        })))
        try:
            async for ev in phase_handler(
                user_message=_MESH_SUBTASK_KICKOFF,
                expertise_level=project["expertise_level"],
                resume_session_id=session.get("sdk_session_id"),
                project_dir=proj_dir,
                project_id=project_id,
            ):
                if _apply_turn_side_effect(project_id, session, project, ev):
                    push(_sse_payload(ev))
        finally:
            db.update_project(project_id)

    return stream_buffered(project_id, drive)


# ── Improver experiment approval (auto-resumes the agent on approve) ──
@router.post("/projects/{project_id}/approve-experiment")
async def approve_experiment(project_id: str):
    """Approve an improver experiment plan and stream the resumed turn.

    Returns SSE: an `experiment_approval_approved` event up front (so
    the UI can clear the pill / panel immediately), followed by the
    resumed improver turn driven by `_IMPROVER_EXPERIMENT_KICKOFF`. The
    kickoff is NOT persisted as a user message. Does NOT advance the
    phase — the experiment runs inside the improver phase.
    """
    project = db.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project["phase"] != "improver":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot approve experiment from phase "
                f"{project['phase']!r}"
            ),
        )

    session = db.get_current_session(project_id)
    if session is None:
        raise HTTPException(
            status_code=500,
            detail="No active session found for the improver phase",
        )

    db.update_project(
        project_id, approval_pending=0, approval_kind=None,
    )

    proj_dir = _project_dir(project)

    async def drive(buffer) -> None:
        push = buffer.push
        push(_sse_payload(StreamEvent("experiment_approval_approved", {
            "status": "approved",
            "auto_resumed": True,
        })))
        try:
            async for ev in run_improver_turn(
                user_message=_IMPROVER_EXPERIMENT_KICKOFF,
                expertise_level=project["expertise_level"],
                resume_session_id=session.get("sdk_session_id"),
                project_dir=proj_dir,
                project_id=project_id,
            ):
                if _apply_turn_side_effect(project_id, session, project, ev):
                    push(_sse_payload(ev))
        finally:
            db.update_project(project_id)

    return stream_buffered(project_id, drive)


# ── Tool permission decisions ──────────────────────────────────────────
@router.post("/projects/{project_id}/permission/{tool_use_id}")
def submit_permission_decision(
    project_id: str,
    tool_use_id: str,
    body: PermissionDecisionBody,
) -> dict:
    """Resolve a pending `can_use_tool` request from the frontend.

    The pending Future is keyed by `tool_use_id` alone (SDK UUIDs are
    globally unique); `project_id` is validated only so the URL
    hierarchy is honest and a request against a deleted project 404s
    cleanly.
    """
    if db.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if body.decision == "allow":
        ok = permissions.resolve_allow(tool_use_id)
    else:
        ok = permissions.resolve_deny(tool_use_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="No pending permission request for that tool_use_id",
        )
    _record_in_turn_buffer(project_id, "permission_resolved", {"tool_use_id": tool_use_id})
    return {"status": "ok", "decision": body.decision}


@router.post("/projects/{project_id}/permission/{tool_use_id}/deny-feedback")
def submit_permission_deny_feedback(
    project_id: str,
    tool_use_id: str,
    body: PermissionDenyFeedbackBody,
) -> dict:
    """Deny a pending tool call with the user's own text as the reason.

    The model receives `body.message` verbatim in place of the canned
    deny message, so the user can steer the agent without first
    interrupting the whole turn.
    """
    if db.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    ok = permissions.resolve_deny_with_feedback(tool_use_id, body.message)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="No pending permission request for that tool_use_id",
        )
    _record_in_turn_buffer(project_id, "permission_resolved", {"tool_use_id": tool_use_id})
    return {"status": "ok", "decision": "deny_with_feedback"}


@router.post("/projects/{project_id}/question/{tool_use_id}/answer")
def submit_question_answer(
    project_id: str,
    tool_use_id: str,
    body: QuestionAnswerBody,
) -> dict:
    """Resolve a paused AskUserQuestion call with the user's answers.

    Mirrors the permission routes: the pending Future is keyed by
    `tool_use_id` alone; `project_id` is validated so a request against
    a deleted project 404s cleanly.
    """
    if db.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    ok = permissions.resolve_answers(
        tool_use_id, body.questions, body.answers, body.response
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="No pending question for that tool_use_id",
        )
    _record_in_turn_buffer(project_id, "question_resolved", {"tool_use_id": tool_use_id})
    return {"status": "ok"}


@router.post("/projects/{project_id}/interrupt")
async def interrupt_turn(project_id: str) -> dict:
    """Interrupt the agent's current turn.

    Calls `ClaudeSDKClient.interrupt()` on the active run. The SDK
    inserts a `[Request interrupted by user]` marker into the session
    transcript itself, so the next resumed turn sees it without our
    help. Partial assistant text and segments already streamed to the
    frontend are persisted normally on the resulting `assistant_turn`
    event.

    Returns `{"interrupted": false}` if no turn was running — clients
    can treat this as a no-op.
    """
    if db.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    ok = await session_registry.interrupt_project(project_id)
    return {"interrupted": ok}


@router.post("/projects/{project_id}/activate")
async def activate_project(project_id: str) -> dict:
    """Mark a project as the active one (frontend calls this on switch/open).

    Drives two things off a single token (see
    `src.agent.paraview_owner` / `session_registry`):
      * ParaView single-tenancy — only the active project may reach the
        live bridge (enforced by the per-worker PreToolUse hook).
      * Session lifecycle — switching away triggers the close-check, so a
        non-active, idle, taskless session is reclaimed. Sessions with a
        running background task stay alive.

    Idempotent and safe regardless of whether any workers exist yet.
    """
    if db.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await session_registry.on_active_project_changed(project_id)
    return {"status": "active", "project_id": project_id}


# ── ParaView lifecycle ─────────────────────────────────────────────────
def _resolve_geometry_path(project_dir: Path, rel_path: str) -> Path:
    """Resolve a project-relative path and confirm containment.

    The user (or an agent) hands us a path like `Cases/baseline/case.foam`; we
    convert to absolute and reject anything that escapes the project
    directory via `..`.
    """
    proj_dir = project_dir.resolve()
    target = (proj_dir / rel_path).resolve()
    try:
        target.relative_to(proj_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path outside project")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {rel_path}")
    return target


@router.post("/projects/{project_id}/paraview/launch")
async def launch_paraview(project_id: str, body: ParaviewLaunchBody) -> dict:
    """Spawn ParaView with the bridge attached.

    409 Conflict if an instance is already alive (for any project).
    The 409 detail names the project that owns the live instance so
    the user knows which window to close.
    """
    project = db.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    proj_dir = _project_dir(project)
    foam_arg: str | None = None
    if body.foam_file:
        foam_arg = str(_resolve_geometry_path(proj_dir, body.foam_file))

    try:
        record = await paraview_lifecycle.launch(
            project_dir=proj_dir,
            project_id=project["id"],
            project_name=project["name"],
            foam_file=foam_arg,
        )
    except paraview_lifecycle.ParaviewAlreadyRunningError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(e),
                "running_for_project": e.project_name,
            },
        )
    except paraview_lifecycle.ParaviewLaunchError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "launched", **record}


@router.post("/projects/{project_id}/paraview/load")
async def load_into_paraview(project_id: str, body: ParaviewLoadBody) -> dict:
    """Load a `.foam` (or other dataset) into the live bridge.

    409 Conflict if no ParaView is running — the frontend's right-click
    handler falls through to /paraview/launch on this signal.
    """
    project = db.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if not paraview_lifecycle.is_running():
        raise HTTPException(
            status_code=409,
            detail="ParaView is not open. Open it first via the toolbar button.",
        )

    target = _resolve_geometry_path(_project_dir(project), body.foam_file)
    result = await paraview_bridge_call("/load_dataset", {"path": str(target)})
    if result.get("is_error"):
        # Surface the bridge's own error (already wrapped in
        # `{content: [{type: text, text: …}], is_error: True}`).
        msg = result["content"][0]["text"]
        raise HTTPException(status_code=502, detail=msg)
    return {"status": "loaded", "path": str(target)}
