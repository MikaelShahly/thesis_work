# Observability — Design Doc

**Goal.** Make the system *justifiably observable*: for any project, be able to show
exactly what each model (and sub-agent) did, thought, was told, was allowed to do, and
what it cost — enough to defend "observability is built into the software" in a thesis.

**Non-goals.** Tamper-evidence / legal chain-of-custody (explicitly not required). We are
not building a WORM store, integrity hashes, or an isolated DB. A user tampering with
their own DB is their problem.

---

## 1. Key decision: capture from the live SDK stream, **not** the on-disk JSONL

We investigated reusing the Claude Code CLI's on-disk session transcripts
(`~/.claude/projects/**/*.jsonl`). **Rejected as the source of truth.** Reasons, all
confirmed against this project's real data:

1. **Scattered.** The app runs the SDK with `cwd = project_dir`
   ([session_manager.py:152](../src/agent/session_manager.py#L152),
   [:369](../src/agent/session_manager.py#L369)), so transcripts are spread across ~119
   per-project / per-phase (`-Case`) directories, not one location.
2. **Sub-agent linkage is fragmented.** A sub-agent's work is written to a *separate*
   `<sessionId>/subagents/agent-*.jsonl` file (57 dirs, 150 files), linked back only
   indirectly via `sourceToolAssistantUUID`. Reconstructing the `parent_tool_use_id`
   nesting our UI already shows (3,974 sub-agent tool segments) would mean cross-file
   reassembly. The **live stream hands us this linkage clean** as `msg.parent_tool_use_id`.
3. **Volatile / not ours.** It's a CLI-owned cache, version-stamped (`version: 2.1.119`),
   subject to cleanup and format change between CLI releases.

Everything we want is already on the live stream we consume in
[`session_manager._run()`](../src/agent/session_manager.py#L435): `AssistantMessage.model`,
per-message `usage`, thinking/text/tool blocks, `parent_tool_use_id`, `ResultMessage`
totals, `SystemMessage` retry/compaction events. The system prompt + config we hold at
[`_build_options`](../src/agent/session_manager.py#L359). **So we extend our own DB from the
live stream; we never parse the JSONL.**

---

## 2. What the session record contains (complete inventory)

From a sweep of 119 app session files + 150 sub-agent files. This is the universe of what
is *possible* to capture.

**Per assistant model-response** (`type: "assistant"`):
`message.model`, `message.id` (msg_…), `requestId` (req_…), `message.stop_reason`,
`message.usage` { `input_tokens`, `output_tokens`, `cache_creation_input_tokens`,
`cache_read_input_tokens`, `cache_creation` (1h/5m split), `output_tokens_details`,
`server_tool_use` (web_search/web_fetch counts), `service_tier`, `inference_geo`, `speed`,
`iterations` }, `timestamp`, `version`, `cwd`, `gitBranch`, `uuid`, `parentUuid`,
content blocks (`thinking` / `text` / `tool_use`), and on failure:
`apiError`, `apiErrorStatus`, `isApiErrorMessage`, `error`, `errorDetails`,
`attributionSkill` (and in sub-agents `agentId`, `attributionAgent`, `attributionPlugin`).

**Per tool result** (`type: "user"` with `tool_result`):
`tool_use_id`, `is_error`, `content`, `toolUseResult` (stdout/stderr/file/…),
`sourceToolUseID`, `sourceToolAssistantUUID`, `timestamp`.

**System / lifecycle** (`type: "system"`):
`subtype`, `compactMetadata` (compaction), and **retry/error**: `cause`, `level`,
`maxRetries`, `retryAttempt`, `retryInMs`, `error`, `logicalParentUuid`.

**Config exposure** (`type: "system"` init + `attachment`): available tools/skills
(`skill_listing`, `deferred_tools_delta`), `permissionMode`.

**Housekeeping (no conversational value — SKIP):**
`ai-title`, `custom-title`, `last-prompt`, `queue-operation`, `file-history-snapshot`,
`mode`. (~50% of lines.)

---

## 3. What we store today

- `messages` (id, session_id, role, content, created_at) — one row per **turn**.
- `message_segments` (kind, content, tool_use_id, tool_name, tool_input, tool_is_error,
  parent_tool_use_id, seq) — text/thinking/tool breakdown.
- `sessions` (id, project_id, phase, sdk_session_id, created_at).
- `projects` (phase, approval_pending/kind, spec_draft, …).
- Compaction stored as a `role="compaction"` message row (pre/post tokens, trigger).

**Captured nowhere:** model, tokens, cost, stop_reason, message/request ids, per-event
timestamps, tool durations, config, system prompt, retries/API errors, sub-agent text.

---

## 4. What to add (the recommendation)

Four additive changes. Nothing existing is removed; the current reload path is untouched.
Each field tagged **[M]** must-have for a defensible thesis claim, **[R]** recommended,
**[D]** depth.

### 4.1 New table `model_calls` — one row per `AssistantMessage`

The core of token/model observability. Grain = one `AssistantMessage` (one API response);
**confirmed correct** because the SDK exposes `usage` per-`AssistantMessage`
([types.py:964-975](../.venv/lib/python3.10/site-packages/claude_agent_sdk/types.py#L964)).
Every field below is a direct attribute of that object — nothing derived, nothing
cross-referenced. **No cost tracking** (explicit decision): store raw tokens + model and
let the reader compute cost if they want.

| column | tag | live source (`AssistantMessage`) |
|---|---|---|
| id, session_id | M | — |
| message_id (the turn's `messages.id`, nullable) | R | turn it belongs to |
| parent_tool_use_id (sub-agent attribution, nullable) | M | `.parent_tool_use_id` |
| model | M | `.model` |
| stop_reason | R | `.stop_reason` |
| input_tokens, output_tokens | M | `.usage` |
| cache_creation_tokens, cache_read_tokens | M | `.usage` |
| service_tier | D | `.usage` |
| anthropic_message_id | R | `.message_id` |
| error (json, nullable) | R | `.error` |
| created_at | M | stream receipt time |

Roll-ups (tokens per turn / phase / project) are `SUM` queries over this table. (`request_id`
dropped — not exposed on the SDK object, only in the JSONL.)

### 4.2 New table `session_config` — one row per session, captured at start

Everything that defines *what the agent was and was allowed to do*. Sourced from
[`_build_options`](../src/agent/session_manager.py#L359) + the `SystemMessage` init.

| column | tag |
|---|---|
| session_id (PK/FK) | M |
| system_prompt (full text) | M |
| system_prompt_sha256 | R |
| model | M |
| effort, thinking_budget, max_turns, permission_mode | M |
| allowed_tools (json), mcp_servers (json), skills (json) | R |
| cwd, git_branch, sdk_version | D |
| created_at | M |

The **system prompt is the single most important addition** — it's the "why it did what it
did," and it exists only in-process at build time (never in the JSONL).

### 4.3 New table `agent_events` — lifecycle / reliability

| column | tag | source (**confirmed reachable in `_run`**) |
|---|---|---|
| id, session_id, created_at | R | — |
| kind: `app_error` \| `api_error` \| `retry` \| `interrupt` \| `permission` | R | see below |
| data (json) | R | the raw payload |

Sources, all confirmed by tracing the error path:
- `app_error` → the existing `StreamEvent("error", {message, recoverable})`, emitted at
  [session_manager.py:557](../src/agent/session_manager.py#L557) (unhandled loop exception)
  and [:596](../src/agent/session_manager.py#L596) (`ResultMessage.is_error`). **This is the
  red text in the UI today.** It is forwarded to SSE but **not** persisted (not in
  `_INTERNAL_EVENTS`, no `db.save` in the event loop) — so it currently **vanishes on
  reload**. Persisting it here is the fix: add one handler in routes' event loop
  (`if ev.type == "error": insert_agent_event(...)`).
- `api_error` → `AssistantMessage.error`
  ([types.py:970](../.venv/lib/python3.10/site-packages/claude_agent_sdk/types.py#L970)) —
  the model call itself; needs a new emit from `_run`.
- `retry` → non-`init` / non-`compact_boundary` `SystemMessage(subtype, data)` — already
  received by `_run`, currently ignored; capture generically.
- `interrupt` → existing turn-interrupt handling; `permission` → hooks.
- `compaction` is **not** here — already stored as the `role="compaction"` message row;
  leave it as-is, don't duplicate.

The three error layers are distinct and all currently non-durable: `app_error` (our
try/except, shown red), `api_error` (the API call failed), `retry` (backoff). Capturing all
three is what lets the write-up say "the system records its own failures, not just the happy
path" — and makes them survive a reload, which today they don't.

### 4.4 Extend `message_segments`

- `started_at`, `ended_at` **[D]** — for `tool` segments → execution **duration** (which
  `checkMesh`/`Bash` took 10 min). Both timestamps are already on the stream (tool_use
  emitted → tool_result returned).
- Sub-agent narration is NOT captured here — it is not on the live stream. See §4.6.

### 4.5 Cost — intentionally not tracked

Decision: we store raw **tokens + model** only. No price map, no `cost_usd` column.
A reader who wants dollars can compute them from tokens + model against Anthropic's
published rates. Keeps the schema and code free of pricing that goes stale.

### 4.6 Sub-agent narration — `subagent_narration` table (record-only, via SubagentStop hook)

**The gap, and the correction.** Sub-agents run *without thinking*, so their interleaved
**text** blocks are their *entire* reasoning trace. The original plan captured these from
the live stream as an `agent_text` segment — but a **live test disproved the premise**: the
CLI does **not** forward sub-agent text to the parent client at all (confirmed — the
sub-agent's distinctive phrases were absent from the DB but present on disk; 0 captured from
the stream). It surfaces sub-agent *tool* activity (→ our tool segments) and the sub-agent's
*final* answer (the `Agent` tool output, already stored), but the *intermediate* narration
exists **only in the sub-agent's on-disk transcript**.

There is also **no live-interleaved path**: no event/hook streams the text as it's produced
(`PreToolUse`/`PostToolUse` carry tool data; `TaskProgress` carries token stats; the message
stream carries no sub-agent text). The only live signal is `SubagentStop`, which fires when
a sub-agent **finishes** and hands over `agent_transcript_path`.

**Decision: capture at completion, persist for the record, do NOT render.** Purely so the
full flow can be inspected later — not shown in the chat.

**How it works.**
- A `SubagentStop` hook (`_on_subagent_stop`, registered alongside the existing
  `PreCompact` / `PreToolUse` hooks) receives `agent_transcript_path`, `agent_id`,
  `agent_type`.
- `_extract_subagent_texts(path)` reads that JSONL and pulls the assistant text blocks in
  order (tolerant of partial lines / a rotated file).
- The hook emits an internal `subagent_narration` event; the API layer persists it to a
  dedicated **`subagent_narration`** table (one row per text block: `session_id`, `agent_id`,
  `agent_type`, `seq`, `content`). Record-only — *not* `message_segments`, so it never
  touches the reload/render path.

**Deliberately skipped:** `parent_tool_use_id` attribution (the `agent_id ↔ Agent tool_use`
mapping) — only needed for UI grouping, which we don't do. `agent_id` + `agent_type` are
enough to identify the sub-agent for later inspection.

---

## 5. Crash-resilience (a free side-benefit)

Today the turn is persisted once, at `assistant_turn` (turn end), so a crash mid-turn
loses everything not yet finalized. Writing `model_calls` rows and segments **as each
model response / segment completes** (which we're already iterating) means a crash loses
at most the single in-flight response. This directly fixes the "I lose a lot on a crash"
problem and is the same code path as the capture above — do them together.

---

## 6. What we explicitly do NOT store

- The on-disk JSONL (rejected — §1).
- Housekeeping records (`ai-title`, `last-prompt`, `queue-operation`,
  `file-history-snapshot`, `mode`).
- Per-token streaming deltas (only completed blocks; deltas are ephemeral and useless
  once the block is done).

---

## 7. Thesis-defensible minimum vs. complete

**Minimum to claim observability ([M] only):** `model_calls` (model, tokens, cost,
parent_tool_use_id) + `session_config` (system prompt, model, config). This answers: *what
model, under what instructions and limits, did what, at what cost* — for the top-level
agent and every sub-agent.

**Complete ([M]+[R]+[D]):** adds latency/duration, request ids, retries/errors,
sub-agent text, service tier. This is "full observability" — recommended, and cheap since
every signal is already on the stream.

---

## 8. Implementation surface (additive, low-risk)

- All capture lives in the existing receive loop
  [`session_manager._run()`](../src/agent/session_manager.py#L435) and `_finalize_turn`;
  config capture at [`_build_options`](../src/agent/session_manager.py#L359).
- New tables only — `messages` / `message_segments` / reload path unchanged, so the
  frontend is untouched. The two segment columns (4.4) are nullable additions.
- Sub-agent `text` capture is **resolved**: it arrives in the assembled
  `AssistantMessage.TextBlock` (no partial streaming for sub-agents), which the loop
  currently drops with `pass`. Capture it there when `ptu is not None` (§4.6).
- Per-`AssistantMessage` `usage` is **resolved**: the SDK exposes `usage`, `model`,
  `message_id`, `stop_reason`, `parent_tool_use_id`, and `error` directly on
  `AssistantMessage` ([types.py:964-975](../.venv/lib/python3.10/site-packages/claude_agent_sdk/types.py#L964)).
  No open SDK questions remain — the schema in §9 is final.

---

## 9. Implementation spec

### 9.1 DDL (matches `db.py` conventions: `IF NOT EXISTS`, TEXT uuid PKs, FK cascade, `CURRENT_TIMESTAMP`)

Add to `init_db()` in [src/db.py](../src/db.py):

```sql
CREATE TABLE IF NOT EXISTS model_calls (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    message_id TEXT,                  -- the turn's messages.id (nullable)
    parent_tool_use_id TEXT,          -- sub-agent attribution; NULL = top-level
    model TEXT NOT NULL,
    stop_reason TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_creation_tokens INTEGER,
    cache_read_tokens INTEGER,
    service_tier TEXT,
    anthropic_message_id TEXT,
    error TEXT,                       -- json of AssistantMessage.error; NULL if ok
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_model_calls_session ON model_calls(session_id);

CREATE TABLE IF NOT EXISTS session_config (
    session_id TEXT PRIMARY KEY,
    system_prompt TEXT,
    system_prompt_sha256 TEXT,
    model TEXT,
    effort TEXT,
    thinking TEXT,                    -- json
    max_turns INTEGER,
    permission_mode TEXT,
    allowed_tools TEXT,               -- json
    mcp_servers TEXT,                 -- json
    skills TEXT,                      -- json
    cwd TEXT,
    git_branch TEXT,
    sdk_version TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL,               -- app_error | api_error | retry | interrupt | permission
    data TEXT,                        -- json
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_agent_events_session ON agent_events(session_id);
```

Additive columns on `message_segments` (via the existing `_ensure_column()` helper, so
old DBs upgrade in place):

```
started_at TIMESTAMP   -- tool segments: set when tool_use emitted
ended_at   TIMESTAMP   -- tool segments: set when tool_result returns  → duration
```

`agent_text` needs **no** schema change — it reuses the existing `kind` column.

### 9.2 Per-event incremental writes (the crash-fix; "save every completed event")

Today persistence is one batched `save_assistant_turn` at the `assistant_turn` event.
Replace with per-event writes, keeping the existing split (session_manager emits events →
routes persists). `session_manager._run` already emits `thinking_text`, `tool_input`,
`tool_output`; add `agent_text` and `model_call` emits. Routes persists each on arrival:

| live event | DB write |
|---|---|
| first segment/text of a turn | `create_assistant_message(session_id) → mid`; reset `seq=0` |
| `tool_input` | INSERT segment (kind=tool, input, `started_at`) at next `seq` |
| `tool_output` | UPDATE that segment by `tool_use_id` (output, is_error, `ended_at`) |
| `thinking_text` | INSERT segment (kind=thinking) |
| `agent_text` (new) | INSERT segment (kind=agent_text) |
| top-level `text` | flush coalesced text as a segment when the next non-text event arrives, else at turn end |
| `model_call` (new, per `AssistantMessage`) | INSERT `model_calls` row |
| `AssistantMessage.error` / non-init `SystemMessage` | INSERT `agent_events` row |
| `assistant_turn` (end) | UPDATE the message row's `content` with the final text only — **no** segment re-insert |

New `db.py` helpers (replacing the single `save_assistant_turn`): `create_assistant_message`,
`append_segment`, `set_tool_output`, `finalize_message_text`, `insert_model_call`,
`insert_session_config`, `insert_agent_event`. `seq` is a per-turn counter so ordering is
preserved; the reload path (`get_segments ORDER BY seq`) is unchanged, so the frontend is
untouched.

**Not per-delta.** Token/thinking deltas are *never* persisted — they coalesce in memory
and write once per *completed* block (≈3–4 row writes per tool cycle, seconds apart). DB
persistence (coarse, per-block) is decoupled from frontend SSE streaming (fine, per-delta),
which is unchanged. No write thrashing.

`session_config` is written once when the `SessionWorker` starts (system prompt + config
are in hand at [`_build_options`](../src/agent/session_manager.py#L359)); dedupe on the
`session_id` PK.

### 9.3 Sequencing / risk

1. **Tables + helpers** (additive, zero behavior change) — ship, verify rows populate.
2. **Switch persistence to per-event** (the write-path restructure) — the one change that
   touches existing behavior; test reload reconstructs identically before/after.
3. **Sub-agent `agent_text`** capture + frontend render (§4.6).

Tests (DB round-trip, reload-equivalence before/after the write-path switch, sub-agent
narration persist+reload) come after this plan is locked, per the project convention.
