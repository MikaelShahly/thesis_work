# AgenticCFD (Agent SDK build) — Architecture

> **Audience**: future coding agents (and humans) who need to come up to speed quickly. Read this first; then look at the source.

---

## 1. What this project is

AgenticCFD is the **end-to-end agentic CFD pipeline**: the user describes a flow problem in natural language, and the system produces, runs, and reports on a complete OpenFOAM 2412 simulation. Five sequential phases, each driven by a specialised LLM agent:

1. **Simulation specification** — converse with the user, produce `simulation_specification.md`
2. **Case builder** — write the OpenFOAM case dictionary
3. **Mesh** — generate `blockMeshDict` / `snappyHexMeshDict`
4. **Improver** — iteratively run + fix the case until it converges
5. **Post-process** — generate the final report

This repository is the **Claude Agent SDK port** of that pipeline. The original (`../agenticCFD_version_2 copy/`) talks to the Anthropic Messages API directly via the `anthropic` Python client. This port replaces the LLM layer with [`claude-agent-sdk`](https://code.claude.com/docs/en/agent-sdk/overview), which subprocesses the Claude Code CLI. Everything outside the LLM layer (FastAPI shell, SSE wiring, React UI, SQLite persistence, project-folder layout) is otherwise the same shape.

The **canonical design document for the broader pipeline**  This document describes the **SDK build** specifically.

---

## 2. Status: what's implemented

| Surface | Status |
|---|---|
| FastAPI app + 6 endpoints | ✅ done |
| React frontend (copied verbatim from v2) | ✅ done |
| SQLite persistence | ✅ done |
| `simulation_spec` phase handler + tool + prompt | ✅ done |
| `case_builder` / `mesh` / `improver` / `post_process` phase handlers | ❌ **not wired** — placeholder configs exist in `PHASE_CONFIGS`; sending a message to a project past `simulation_spec` returns HTTP 400 |
| Subagents / SDK skills | ❌ not used (simulation_spec is a single conversational agent — nothing to delegate). The architecture is set up so they drop in for the later phases. |
| Tracing / observability | ❌ intentionally omitted |
| Tests | ❌ not yet written; `tests/basic` and `tests/production` directories exist as scaffolds |

If you only have time to look at three files, look at:

- [src/agent/core.py](../src/agent/core.py) — the SDK wrapper and the message-stream → SSE event translation
- [src/api/routes.py](../src/api/routes.py) — the 6 HTTP endpoints and the SSE event loop
- [src/config.py](../src/config.py) — the per-phase registry that drives everything

---

## 3. Architecture at a glance

```
┌──────────────────────────────────────────────────────────────────┐
│ React frontend (Vite, :5173)                                     │
│   sidebar | chat-col | (handle | spec-panel)                     │
│   POSTs / GETs /api/* + opens SSE on /api/projects/{id}/messages │
└─────────────────────────┬────────────────────────────────────────┘
                          │ HTTP + SSE
┌─────────────────────────▼────────────────────────────────────────┐
│ FastAPI (uvicorn, :8000)                                         │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ src/api/routes.py                                            │ │
│  │   project CRUD · approve-spec · send-message (SSE)           │ │
│  └─────────┬───────────────────────────────────────────────────┘ │
│            │ dispatches by project.phase                          │
│  ┌─────────▼───────────────────────────────────────────────────┐ │
│  │ src/phases/simulation_spec.py                                   │ │
│  │   reads PHASE_CONFIGS, builds tooling, calls run_turn()      │ │
│  └─────────┬───────────────────────────────────────────────────┘ │
│  ┌─────────▼───────────────────────────────────────────────────┐ │
│  │ src/agent/core.py                                            │ │
│  │   opens ClaudeSDKClient, walks receive_response(), maps      │ │
│  │   SDK messages → our StreamEvent vocabulary                  │ │
│  └─────────┬───────────────────────────────────────────────────┘ │
│            │ subprocess via stdio pipe                            │
│  ┌─────────▼───────────────────────────────────────────────────┐ │
│  │ claude-agent-sdk → spawns `claude` CLI subprocess            │ │
│  │   owns conversation state, compaction, tool execution        │ │
│  │   custom tools registered via SDK MCP server (in-process)    │ │
│  └─────────┬───────────────────────────────────────────────────┘ │
│            │ HTTPS to Anthropic — auth via Claude Code subscription │
│  ┌─────────▼─────────┐  ┌───────────────────────────────────────┐ │
│  │ SQLite            │  │ projects/{folder_name}/                │ │
│  │ data/agenticcfd.db│  │   simulation_specification.md             │ │
│  │ projects/sessions/│  │   (later: case/, mesh/, reports/)      │ │
│  │  messages         │  └───────────────────────────────────────┘ │
│  └───────────────────┘                                              │
└─────────────────────────────────────────────────────────────────────┘
```

Key shape: each user turn = one `ClaudeSDKClient` opened, one `query()` call, one walk of `receive_response()`, one close. **The SDK owns conversation state.** We resume across turns by passing `resume=<sdk_session_id>` to `ClaudeAgentOptions`; the local `messages` table is purely a UI mirror, never replayed back to the LLM.

---

## 4. Folder layout

```
agenticCFD_sdk/
├── src/
│   ├── __init__.py
│   ├── config.py                  # PHASE_CONFIGS, paths, host/port
│   ├── db.py                      # SQLite schema + accessors
│   ├── api/
│   │   ├── __init__.py
│   │   ├── app.py                 # FastAPI app, lifespan, CORS, env-strip
│   │   └── routes.py              # 6 endpoints, SSE event loop
│   ├── agent/
│   │   ├── __init__.py
│   │   └── core.py                # run_turn(), SDK wrapper, StreamEvent translation
│   ├── tools/
│   │   ├── __init__.py            # build_tooling(): MCP server + allowed_tools
│   │   └── present_spec.py        # @tool present_specification
│   └── phases/
│       ├── __init__.py
│       └── simulation_spec.py        # reads PHASE_CONFIGS["simulation_spec"], delegates to run_turn
├── prompts/
│   └── simulation_spec.txt           # system prompt template, formatted with {expertise_level}
├── frontend/                      # React + Vite (verbatim from v2)
├── data/                          # SQLite DB, gitignored, created at runtime
├── projects/                      # per-project work folders, gitignored, created on POST /projects
├── docs/
│   ├── architecture.md            # this file
│   └── roadmap.md                 # future phases + broader pipeline vision
├── tests/                         # basic/ and production/ split; empty
├── main.py                        # uvicorn entrypoint
├── pyproject.toml                 # uv-managed Python deps
├── uv.lock
├── README.md                      # human onboarding (install + run)
├── CLAUDE.md                      # project conventions for AI agents
└── .gitignore
```

---

## 5. Per-component breakdown

### 5.1 `src/api/app.py` — FastAPI shell + auth-key strip

[src/api/app.py](../src/api/app.py)

Responsibilities:
- Construct the FastAPI app with CORS open to `http://localhost:5173` (Vite dev) and `:3000` (fallback)
- Mount the router at `/api`
- Initialise the SQLite schema in the lifespan
- **Strip `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` from `os.environ`** at module-import time *and* in the lifespan

Why the env strip is in two places:
- **Import-time** catches anything that snapshots env on first load (some third-party packages do)
- **Lifespan** is defence-in-depth in case something else has set them between import and request handling

The strip is non-negotiable per the auth model in §10. Do not remove it. Do not load `.env`. Do not add `python-dotenv` back.

### 5.2 `src/api/routes.py` — the 6 endpoints

[src/api/routes.py](../src/api/routes.py)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/projects` | Create project. Returns project summary + materialises `projects/{folder_name}/` immediately. |
| GET | `/api/projects` | List projects (most-recently-updated first). |
| GET | `/api/projects/{id}` | Project detail + flattened chat history for the UI. |
| DELETE | `/api/projects/{id}` | Delete project; cascades sessions/messages and removes `projects/{folder_name}/`. Filesystem first so a partial failure leaves the DB row visible. |
| POST | `/api/projects/{id}/messages` | Send a user message. Returns an SSE stream. |
| POST | `/api/projects/{id}/approve-spec` | Approve the current spec draft. Writes `simulation_specification.md`, advances `phase` to `case_builder`, creates a fresh session. Returns plain JSON; the frontend renders the transition client-side. |

The send-message handler is the only SSE endpoint. Its event loop:

1. Look up the project; resolve handler from `PHASE_HANDLERS` (currently only `simulation_spec`).
2. Get / create the current session; persist the user's message (UI mirror) before streaming, so a dropped connection doesn't lose the input.
3. Open the phase handler async generator. For each `StreamEvent`:
   - `sdk_session_id` (internal) → persist to `sessions.sdk_session_id`
   - `assistant_text` (internal) → persist as a `messages` row
   - `specification_presented` → persist `markdown` to `projects.spec_draft`, then forward to client
   - everything else → forward to client as SSE
4. Bump `projects.updated_at` in `finally`.

Internal events (`_INTERNAL_EVENTS = {"sdk_session_id", "assistant_text"}`) are consumed by the API layer and never reach the browser.

### 5.3 `src/agent/core.py` — the SDK wrapper

[src/agent/core.py](../src/agent/core.py)

`run_turn()` is the single entry point. Its contract:

```
inputs:
  user_message       — the user's text
  system_prompt      — fully composed (already formatted with expertise_level)
  model              — model id, e.g. "claude-sonnet-4-5"
  allowed_tools      — list[str] for ClaudeAgentOptions.allowed_tools
  mcp_servers        — dict for ClaudeAgentOptions.mcp_servers
  resume_session_id  — str | None; if str, resume that SDK session
  effort, thinking, hooks — per-phase tunables; None defers to SDK default

yields:
  StreamEvent objects (see vocabulary in §6)
```

Inside, it:
1. Builds `ClaudeAgentOptions` (see §7 for the constants we set)
2. Opens `ClaudeSDKClient(options=options)` as a context manager
3. Calls `client.query(user_message)` once
4. Walks `client.receive_response()`, dispatching by message type:

   | SDK message | Action |
   |---|---|
   | `SdkStreamEvent` | Translate `event.event` (raw Anthropic stream dict) into `text_delta` / `thinking_started` / `tool_started`. Capture `session_id`. |
   | `SystemMessage(subtype="init")` | Capture `session_id` from `data["session_id"]`. |
   | `AssistantMessage` | Walk content blocks: collect `TextBlock.text` for DB persistence; if `ToolUseBlock` is `present_specification`, emit `specification_presented` with the markdown from `block.input`. |
   | `UserMessage` | If content has `ToolResultBlock`s, emit `tool_completed`. |
   | `ResultMessage` | Capture `session_id`; emit accumulated `assistant_text` (internal) + `sdk_session_id` (internal); emit `turn_complete` and return. |

**Critical invariant — the StreamEvent / AssistantMessage split**: `include_partial_messages=True` causes the SDK to yield BOTH token-level `StreamEvent`s during generation AND the assembled `AssistantMessage` afterwards. We deliberately use them for non-overlapping purposes:

- `StreamEvent` → emit `text_delta` to the frontend (live token-by-token UI)
- `AssistantMessage` → mine for tool-use input (need the assembled `input` dict) and accumulate text for DB persistence (emitted later as the *internal* `assistant_text` event, never forwarded)

Don't "fix" the apparent duplication. There's a comment in the file saying the same thing. Listen to it.

### 5.4 `src/tools/` — custom tools + tooling registry

[src/tools/__init__.py](../src/tools/__init__.py), [src/tools/present_spec.py](../src/tools/present_spec.py)

Two flavours of tool live behind one front door:

- **Built-in Claude Code tools** (`WebSearch`, `Bash`, `Read`, `Write`, `Edit`, `Glob`, `Grep`) — referenced verbatim by name in `allowed_tools`.
- **Custom Python tools** — defined with `@tool` from `claude_agent_sdk`, bundled into one **SDK MCP server** named `cfd` via `create_sdk_mcp_server`, and referenced as `mcp__cfd__<tool_name>` in `allowed_tools`.

`build_tooling(tool_names)` is the only public function. It splits the input list, builds the MCP server lazily (only if there are custom tools), and returns `(allowed_tools, mcp_servers)` ready to feed straight into `ClaudeAgentOptions`.

Currently one custom tool: `present_specification`. When the agent calls it:
- The Python body (in [src/tools/present_spec.py](../src/tools/present_spec.py)) just returns a confirmation string the agent sees as the tool result.
- The actual UI side-effect (open the spec panel, populate it with markdown) is driven by the `agent/core.py` layer noticing the `ToolUseBlock` in the AssistantMessage and emitting `specification_presented`. The tool body itself doesn't touch any UI state.

### 5.5 `src/phases/simulation_spec.py` — phase handler

[src/phases/simulation_spec.py](../src/phases/simulation_spec.py)

Thin glue: read `PHASE_CONFIGS["simulation_spec"]`, format the prompt template with `{expertise_level}`, build tooling, call `run_turn()`. That's the entire file. Future phase handlers should match this shape.

### 5.6 `src/db.py` — SQLite

[src/db.py](../src/db.py)

Three tables; see §8 for the full schema. Things to know:

- **`messages.content` is plain text**, not nested JSON content blocks. This table is a UI mirror only — the SDK owns the real conversation state. Don't replay these rows back to the LLM.
- **`sessions.sdk_session_id`** is the resume key. Captured on the first turn (from `SystemMessage(subtype="init")` or `ResultMessage.session_id`), persisted, and passed back on every subsequent turn via `ClaudeAgentOptions.resume`.
- **Project folders use `slugify(name)`** to derive `folder_name`. The slug is enforced unique via a SQL index. Frontend prevents most conflicts at input time; the index is defence-in-depth.

`get_full_chat_history(project_id)` flattens messages across sessions and inserts `phase_transition` markers between sessions of different phases — this is what the frontend reads on page load to redraw the chat.

### 5.7 `src/config.py` — phase registry

[src/config.py](../src/config.py)

`PHASE_CONFIGS` is the **only place** you tune agent behaviour. Per-phase keys:

| Key | Type | Purpose |
|---|---|---|
| `model` | `str` | Forwarded to `ClaudeAgentOptions.model`. |
| `prompt_template` | `str` | Filename in `prompts/`, formatted with `{expertise_level}`. |
| `tools` | `list[str]` | Mix of built-in names (`"WebSearch"`) and custom tool IDs (`"present_specification"`). Resolved by `build_tooling()`. |
| `effort` | `"low" \| "medium" \| "high" \| "max" \| None` | Forwarded as-is. `None` = SDK default. |
| `thinking` | `dict \| None` | Extended-thinking config: `{"type": "enabled", "budget_tokens": N}` / `{"type": "adaptive"}` / `{"type": "disabled"}` / `None`. |
| `hooks` | `dict[str, list[HookMatcher]] \| None` | Maps hook event (`"PreToolUse"`, `"PostToolUse"`, `"Stop"`, …) to matchers. None = no hooks. |

Currently `simulation_spec` is the only phase with non-default values: `thinking` is enabled at `budget_tokens=4096` to match v2's behaviour. The other phases are placeholders with `None` across the board.

Adding a new tool to a phase is a two-step process:
1. Register the Python function in [src/tools/__init__.py](../src/tools/__init__.py)'s `_CUSTOM_TOOLS` (custom tool) — or just add the built-in name to the phase's `tools` list (built-in).
2. Add the tool's string ID to the phase's `tools` list in `PHASE_CONFIGS`.

### 5.8 `frontend/` — React UI

The frontend is **copied verbatim from v2**. No changes to component code, styles, or hooks. The SSE event names this backend emits match what `frontend/src/hooks/useAgentStream.js` consumes:

- emitted by us: `text_delta`, `thinking_started`, `tool_started`, `tool_completed`, `specification_presented`, `turn_complete`, `error`
- consumed by the frontend's reducer: `text_delta`, `thinking_started`, `tool_started`, `status`, `specification_presented`, `turn_complete`, `error`, plus client-internal `history_loaded` / `user_sent` / `set_accept_mode` / `dismiss_accept` / `clear_pending_action` / `spec_approved`

The `tool_completed` event we emit is harmlessly ignored (no reducer case). `status` we don't currently emit; reserved for future use.

For UI design intent (component hierarchy, layout grid, spec-review flow, theme/accent system, slugify rules, expertise-level cards), see `../agenticCFD_version_2 copy/docs/agenticCFD_archtectire_final_2_.md` §9 and `../agenticCFD_version_2 copy/docs/AgenticCFD_Design (2).jsx` (the visual reference).

---

## 6. SSE event vocabulary

Forwarded to the frontend (these are the public contract):

| Event | Payload | Meaning |
|---|---|---|
| `thinking_started` | `{}` | The agent began reasoning. |
| `text_delta` | `{"content": str}` | A response token. |
| `tool_started` | `{"tool": str}` | A tool call began. Tool name is the bare suffix (`present_specification`, `WebSearch`), not the `mcp__cfd__…` form. |
| `tool_completed` | `{}` | A tool call returned. (Frontend currently ignores.) |
| `specification_presented` | `{"markdown": str}` | The agent called `present_specification`. The API layer also persists this markdown to `projects.spec_draft`. |
| `turn_complete` | `{"stop_reason": str}` | The turn finished. |
| `error` | `{"message": str, "recoverable": bool}` | Something failed. |
| `status` | `{"message": str}` | Reserved; not currently emitted. |

Internal events (consumed by the API layer, never sent to the client — defined in `_INTERNAL_EVENTS` in [src/api/routes.py](../src/api/routes.py)):

| Event | Payload | Side effect |
|---|---|---|
| `sdk_session_id` | `{"session_id": str}` | `sessions.sdk_session_id` updated. |
| `assistant_text` | `{"content": str}` | `messages` row inserted (role=assistant). |

---

## 7. ClaudeAgentOptions constants we set

In [src/agent/core.py](../src/agent/core.py), every `ClaudeSDKClient` is opened with:

```python
ClaudeAgentOptions(
    system_prompt=system_prompt,           # phase-supplied
    model=model,                           # phase-supplied
    allowed_tools=allowed_tools,           # phase-supplied
    mcp_servers=mcp_servers,               # phase-supplied
    permission_mode="dontAsk",             # see §7.1
    include_partial_messages=True,         # see §7.2
    resume=resume_session_id,              # SDK session resumption
    setting_sources=[],                    # see §7.3
    max_turns=30,                          # see §7.4
    effort=effort,                         # phase-supplied (None → SDK default)
    thinking=thinking,                     # phase-supplied (None → SDK default)
    hooks=hooks,                           # phase-supplied (None → no hooks)
)
```

### 7.1 `permission_mode="dontAsk"`

Strictly enforces `allowed_tools`: anything not on the list is denied without a prompt. **Do not change to `"bypassPermissions"`** — that mode approves *every* tool the CLI knows about, ignoring `allowed_tools` entirely. We want the allowlist to be load-bearing.

### 7.2 `include_partial_messages=True`

Enables `StreamEvent` emission so we can stream tokens to the UI. See the StreamEvent / AssistantMessage split discussion in §5.3 — getting both is intentional, not a bug.

### 7.3 `setting_sources=[]`

Disables loading of the developer's local `~/.claude/`, project `.claude/`, and `CLAUDE.md` files into the SDK subprocess. We want a clean, deterministic agent environment regardless of who's running the dev server.

### 7.4 `max_turns=30`

Bounds runaway agent loops within a single user turn. Generous for spec-gathering (a few `WebSearch` calls + one `present_specification` shouldn't come close).

### 7.5 What we deliberately do NOT set

- **`max_budget_usd`** — would risk surprise mid-conversation cutoffs. Turn cap is enough.
- **`can_use_tool` callback** — `dontAsk` does the same job declaratively.
- **`env`** — we don't pass any env to the subprocess. The SDK inherits `os.environ` (minus the stripped API keys; see §10).

---

## 8. Database schema

```sql
CREATE TABLE projects (
    id TEXT PRIMARY KEY,                                    -- uuid
    name TEXT NOT NULL,                                     -- user-facing
    folder_name TEXT NOT NULL UNIQUE,                       -- slugified, on-disk
    phase TEXT NOT NULL DEFAULT 'simulation_spec',
    expertise_level TEXT NOT NULL DEFAULT 'intermediate',
    spec_draft TEXT,                                        -- latest markdown awaiting approval
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sessions (
    id TEXT PRIMARY KEY,                                    -- our uuid
    project_id TEXT NOT NULL,
    phase TEXT NOT NULL,                                    -- which phase this session belongs to
    sdk_session_id TEXT,                                    -- the SDK's session_id, NULL until first turn completes
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE messages (
    id TEXT PRIMARY KEY,                                    -- our uuid
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,                                     -- 'user' | 'assistant'
    content TEXT NOT NULL,                                  -- plain text — UI display only
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
```

Differences from v2:
- v2's `messages.content_json` (nested Anthropic content blocks, including thinking + signatures + tool_use + tool_result) is **gone**. Replaced by plain-text `messages.content` since the SDK owns conversation state and we never replay these rows.
- `sessions.sdk_session_id` is new — the resume key for `ClaudeAgentOptions.resume`.

---

## 9. Data flow per turn

```
USER types in composer
        ↓
frontend POST /api/projects/{id}/messages  body={"content": "..."}
        ↓
routes.send_message:
  · load project, resolve PHASE_HANDLERS[project.phase]
  · get_current_session (or create one)
  · save_message(role="user", content=body.content)        ← UI mirror persisted FIRST
  · update_project(id) (bump updated_at)
        ↓
phases.simulation_spec.run_simulation_spec_turn(...)
        ↓
agent.core.run_turn(...):
  · ClaudeAgentOptions(... resume=session.sdk_session_id ...)
  · async with ClaudeSDKClient(options) as client:
      await client.query(user_message)
      async for msg in client.receive_response():
        ─ SdkStreamEvent       → translate event["type"] → yield StreamEvent("text_delta" | "thinking_started" | "tool_started")
        ─ SystemMessage(init)  → capture session_id
        ─ AssistantMessage     → collect TextBlock text; if ToolUseBlock is present_specification, yield specification_presented
        ─ UserMessage          → if ToolResultBlock present, yield tool_completed
        ─ ResultMessage        → yield assistant_text (internal), sdk_session_id (internal), turn_complete
        ↓
back in routes.send_message:
  · sdk_session_id    → update_session(sdk_session_id=...)
  · assistant_text    → save_message(role="assistant", content=...)
  · specification_presented → update_project(spec_draft=markdown)  THEN forward to client
  · everything else (text_delta, thinking_started, tool_started, tool_completed, turn_complete, error)
                          → SSE: event:<type>\ndata:<json>\n\n
        ↓
frontend useAgentStream reducer dispatches by ev.event
        ↓
UI renders streamed tokens, opens spec panel on specification_presented, swaps loader→brand on turn_complete
```

If the user clicks **"Yes, proceed"** in the AcceptPanel:
- frontend POST `/api/projects/{id}/approve-spec`
- routes.approve_spec writes `projects/{folder_name}/simulation_specification.md`, creates a new session for `case_builder`, updates `projects.phase = "case_builder"`, returns transition JSON
- frontend renders the approval badge, PhaseDivider, updates the phase pill — all client-side
- subsequent messages currently HTTP 400 because there's no `case_builder` handler yet

---

## 10. Auth model

**This project authenticates via the Claude Code subscription only.** Never via an API key.

How it's enforced:
1. [src/api/app.py](../src/api/app.py) calls `os.environ.pop("ANTHROPIC_API_KEY", None)` and `os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)` at module import and again in lifespan.
2. The SDK builds the subprocess env via `{**os.environ_minus_CLAUDECODE, ..., **options.env}` (see [transport/subprocess_cli.py:407](../.venv/lib/python3.10/site-packages/claude_agent_sdk/_internal/transport/subprocess_cli.py#L407)). With the keys stripped from our process, they're not in the inherited env, so the subprocess never sees them.
3. The Claude Code CLI's auth precedence is: API key → OAuth token → CLI's stored OAuth credentials (`~/.claude/.credentials.json`). With keys stripped, it falls through to the stored credentials from `claude` login.

**Why this matters**: when an `ANTHROPIC_API_KEY` is present in the env, the CLI silently prefers it over OAuth. That would charge usage to the API account instead of the subscription, and could leak the key into the subprocess's process listing. The strip is the only reliable guarantee.

**Do not**:
- Add `python-dotenv` back as a dep
- Add a `.env` or `.env.example` file containing `ANTHROPIC_API_KEY`
- Pass `env={"ANTHROPIC_API_KEY": ...}` to `ClaudeAgentOptions`
- Write tests that monkeypatch the keys back in (they'd defeat the production strip path silently)

---

## 11. Adding a new phase (concrete steps)

When the case-builder/mesh/improver/post-process phases come online, follow this pattern:

1. **Update `PHASE_CONFIGS`** in [src/config.py](../src/config.py) with the phase's `model`, `prompt_template`, `tools`, `effort`, `thinking`, `hooks`. Already stubbed for the four downstream phases — fill in real values.

2. **Drop the prompt template** in `prompts/<phase>.txt`. The current prompt template uses `{expertise_level}` as a single substitution variable; downstream phases will likely need additional ones (e.g. `{simulation_specification}` injected from the upstream artifact).

3. **Implement any custom tools** in `src/tools/<tool_name>.py` and register them in `_CUSTOM_TOOLS` in [src/tools/__init__.py](../src/tools/__init__.py). For built-in Claude Code tools (`Bash`, `Read`, `Write`, `Edit`, `Glob`, `Grep`), just add the name to the phase's `tools` list — no Python code needed.

4. **Write a phase handler** at `src/phases/<phase>.py` matching the [simulation_spec.py](../src/phases/simulation_spec.py) pattern. It should be 30–40 lines: read config, format prompt with whatever variables that phase needs, build tooling, call `run_turn()` and yield through.

5. **Wire it into `PHASE_HANDLERS`** in [src/api/routes.py](../src/api/routes.py).

6. **Decide on subagents/skills** if applicable. The improver phase in particular is a natural fit for subagents — e.g., a "log analyser" subagent that takes a failed run's `log.simpleFoam` and returns a concise diagnosis. Define them via `ClaudeAgentOptions.agents` and reference them in the system prompt. For SDK skills, list them in `ClaudeAgentOptions.skills`.

7. **Inter-phase context**: the upstream artifact (e.g. the approved `simulation_specification.md`) should be **embedded in the new phase's system prompt**, not passed as a tool input or message. This matches the v2 design (§10.1 of the v2 architecture doc) and keeps the artifact immune to compaction.

8. **Spec-approval-style transition endpoint**: if the phase has an explicit "user approves and we move on" gesture, add a sibling to `/approve-spec`. If the phase auto-advances on completion (e.g. improver finishes when convergence criteria are met), the phase handler should emit a `phase_changed` event and the API layer should advance `projects.phase` itself.

---

## 12. Adding a new custom tool (concrete steps)

1. Create `src/tools/<tool>.py`:
   ```python
   from typing import Any
   from claude_agent_sdk import tool

   @tool(
       "tool_name",                          # what the LLM sees
       "Tool description...",                # what the LLM reads
       {"arg1": str, "arg2": int},           # Python-type schema (SDK converts to JSON Schema)
   )
   async def tool_name(args: dict[str, Any]) -> dict[str, Any]:
       # ... do the work ...
       return {"content": [{"type": "text", "text": "result string"}]}
   ```

2. Register it in [src/tools/__init__.py](../src/tools/__init__.py)'s `_CUSTOM_TOOLS` dict, keyed by the tool's name.

3. Add the tool's string name to the relevant phase's `tools` list in `PHASE_CONFIGS`.

4. If the tool's invocation should drive a UI side effect (the way `present_specification` opens the spec panel), add a branch in the `AssistantMessage` handler in [src/agent/core.py](../src/agent/core.py) that detects the `ToolUseBlock` by name and emits a custom `StreamEvent`. Then handle that event in [src/api/routes.py](../src/api/routes.py)'s SSE loop and in `frontend/src/hooks/useAgentStream.js`'s reducer.

---

## 13. Invariants (do not break)

These are load-bearing decisions; deviating from them will break things in non-obvious ways.

1. **Subscription auth only.** No API key, ever. See §10.
2. **The SDK owns conversation state.** Don't replay the local `messages` rows back to the LLM. The DB is a UI mirror.
3. **`sessions.sdk_session_id` is captured per turn and used as `resume` next turn.** The SDK guarantees session_id stability across resumes.
4. **`StreamEvent` and `AssistantMessage` carry overlapping data; we use them for non-overlapping purposes.** Don't try to deduplicate by reading text from only one source. See §5.3.
5. **`permission_mode="dontAsk"`** — not `"bypassPermissions"`. The allowlist is load-bearing.
6. **`setting_sources=[]`** — we don't want the developer's local Claude Code config bleeding into the agent.
7. **Tool-result UserMessages don't carry the tool name.** When emitting `tool_completed`, you can't reliably name the tool from the result alone — the corresponding `tool_started` event already carried the name; the frontend can pair them by ordering.
8. **Custom MCP tools are referenced as `mcp__<server>__<tool>`** in `allowed_tools`. Double underscores. Server name is `cfd` (see `MCP_SERVER_NAME` in [src/tools/__init__.py](../src/tools/__init__.py)).
9. **Project folders use `slugify(project_name)`.** The slug must match what the JS version in `frontend/src/lib/slugify.js` produces — they're independently implemented but must agree.
10. **Frontend SSE event names are part of the contract.** Renaming an event in the backend without updating `frontend/src/hooks/useAgentStream.js` breaks the UI silently.

---

## 14. Things intentionally NOT done

So future agents don't waste time "fixing" them:

- **No tracing / observability.** Claude Code has native OTEL support and the SDK propagates W3C trace context automatically — but no tracing is wired up here, by user request.
- **No `.env` file, no `python-dotenv`.** Auth is subscription-only; there are no secrets to load.
- **No FastAPI concurrency limits / semaphores.** Single-user dev project; YAGNI.
- **No `effort`, `thinking`, or `hooks` defaults beyond `simulation_spec`'s thinking budget.** Add per-phase as needed.
- **No tests yet.** The `tests/basic/` and `tests/production/` folders are scaffolds. Project conventions (see `CLAUDE.md`) mandate the split when tests do land: `basic/` for syntax/mock; `production/` for true round-trips (DB persistence, SDK session resumption, tool-dispatch event emission).
- **No subagents or SDK skills for `simulation_spec`.** It's a single conversational agent; nothing to delegate. Reserved for the downstream phases.

---

## 15. Source-of-truth pointers

- **Project conventions for AI agents** → [CLAUDE.md](../CLAUDE.md)
- **Human install + run guide** → [README.md](../README.md)
- **v2 architecture** (broader pipeline vision, UI/UX intent) → `../agenticCFD_version_2 copy/docs/agenticCFD_archtectire_final_2_.md`
- **v2 visual design reference** → `../agenticCFD_version_2 copy/docs/AgenticCFD_Design (2).jsx`
- **v2 implementation plan** (phase 1 build sequence) → `../agenticCFD_version_2 copy/docs/phase_1_implementation_plan.md`
- **Roadmap for the four downstream phases of THIS port** → [docs/roadmap.md](roadmap.md)
- **Claude Agent SDK docs** → https://code.claude.com/docs/en/agent-sdk/
