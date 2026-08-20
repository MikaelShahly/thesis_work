# AgenticCFD (Agent SDK build) — Project State Snapshot

> **Purpose**: hand this to a fresh LLM (or human) with no prior context and let
> them discuss design / ideation against the project as it stands today.
> Captures the *current* implementation, not the original architectural
> intent — where the two diverge, the code wins.
>
> **Companion docs**: [architecture.md](architecture.md) is the original design
> document (stale on many points). The earlier planning docs (roadmap,
> case-builder plan, mesh implementation plan + status) have been removed —
> the code is now the only source of truth. Where this snapshot and the code
> disagree, the code wins.

---

## 1. What this project is

AgenticCFD is an **end-to-end agentic CFD pipeline**. The user describes a flow
problem in natural language; the system runs a five-phase agent pipeline that
produces, runs, and reports on a complete OpenFOAM 2412 simulation.

```
[1. Simulation Spec]   → Specification/simulation_specification.md
        ↓ user approves (explicit, via present_specification + /approve-spec)
[2. Case Builder]   → Case/{0,constant,system}/...        (no mesh dictionaries)
        ↓ user approves (request_approval + /approve-case)
        ↓ outgoing agent writes handoffs/case_builder.md, calls commit_phase_advance
[3. Mesh]           → Case/system/{blockMeshDict, snappyHexMeshDict, ...}
                      Case/constant/polyMesh/             (after running mesher)
                      ParaView visualisation alongside
        ↓ user approves each sub-step (request_subtask_approval + /approve-mesh-step)
        ↓ user approves the final mesh (request_phase_advance + /approve-mesh-phase-advance)
        ↓ outgoing agent writes handoffs/mesh_agent.md, calls commit_phase_advance
[4. Improver]       → iteratively run experiments + fix the case until convergence
        ↓ user approves each experiment plan   (request_experiment_approval + /approve-experiment)
        ↓ user approves mesh changes mid-run   (request_mesh_approval + /approve-mesh-step)
        ↓ user approves the final result       (request_phase_advance + /approve-improver-phase-advance)
        ↓ outgoing agent writes handoffs/improver_agent.md, calls commit_phase_advance
[5. Post-process]   → Reports/report.md + plots                          (NOT YET BUILT)
```

Each terminal phase transition is a *two-step* gesture: the user approves
the artifact, and then the outgoing agent runs one more turn — driven by a
backend-owned trigger message — to write `handoffs/<phase>.md` (a brief
agent-to-agent note capturing decisions, assumptions, and useful reference
material the next agent can't recover from reading files alone) and to
call `commit_phase_advance`. That tool call is what actually flips the
phase in the DB. A safety net auto-advances if the agent forgets to call
the tool, so the user is never stuck mid-approval.

The user experiences **one continuous chat**; internally each phase is a
fresh agent session with its own system prompt, model, tools, and sub-agents.

This repository is the **Claude Agent SDK port** of an earlier project that
talked to the Anthropic Messages API directly. The LLM layer is now
[`claude-agent-sdk`](https://code.claude.com/docs/en/agent-sdk/overview), which
subprocesses the Claude Code CLI. Everything else (FastAPI shell, SSE wiring,
React UI, SQLite persistence, project-folder layout) is the same shape as
before.

---

## 2. Status at a glance

| Surface | Status | Notes |
|---|---|---|
| FastAPI app + endpoints | shipped | 20 endpoints (project CRUD, files, file content, geometry upload, messages SSE, approve-spec/-case/-mesh-step/-experiment/-mesh-phase-advance/-improver-phase-advance, permission decide / deny-feedback, question answer, interrupt, ParaView launch/load) |
| SSE streaming layer | shipped | Token-level deltas, tool input/output, thinking, file_written, permission_requested, approval flows, interrupt-aware turn_complete |
| SQLite persistence | shipped | Four tables (projects, sessions, messages, message_segments); idempotent migrations |
| `simulation_spec` phase | shipped | Sonnet 4.5, adaptive thinking, `present_specification` + `WebSearch` + `WebFetch` |
| `case_builder` phase | shipped | Sonnet 4.6, Read/Write/Edit/Glob/Grep/Bash + `Agent` + `request_approval` + `WebFetch`; sub-agent for OpenFOAM source exploration; cwd pinned to `Case/` |
| `mesh` phase | shipped (with known issues) | Opus 4.6, adaptive thinking, cwd=project root; two approval tools (sub-step + phase-advance); ParaView read verbs + `paraview_exec` exposed; two sub-agents (openfoam explorer + ParaView operator) |
| `improver` phase | shipped (behaviour still being polished) | Opus 4.6, adaptive thinking, cwd=project root, `max_turns=20000`; three approval tools (experiment + mesh + phase-advance); ParaView read **and** write verbs + `paraview_exec` exposed (writes/exec gated); one sub-agent (`cfd_general_purpose`) |
| `post_process` phase | stub only | Placeholder `PHASE_CONFIGS["post_process"]`; no handler, **and its `prompt_template` `post_process.txt` does not exist on disk** (would fail if reached) |
| Sub-agent infrastructure | shipped | `SUBAGENT_REGISTRY` + `build_subagents()` (returns agents dict **and** MCP tool union); three sub-agents (`openfoam2412_repository_explore`, `paraview_operator`, `cfd_general_purpose`) |
| Context-compaction surfacing | shipped | `PreCompact` hook → `compaction_started`; SDK `compact_boundary` SystemMessage → `compaction_complete` (pre/post token counts); persisted as a `role="compaction"` message row so the divider survives reload |
| `AskUserQuestion` flow | shipped | simulation_spec exposes the built-in `AskUserQuestion` tool (gated); `can_use_tool` surfaces it as `question_requested`; `QuestionPanel` collects answers; `/question/{id}/answer` resolves the Future |
| Tool-permission gate | shipped | `permission_mode="default"` + `can_use_tool` callback + Future registry + HTTP route + UI panel + **deny-with-feedback** path |
| Turn interrupt | shipped | `/interrupt` HTTP route + `active_runs` registry + SDK-side `client.interrupt()`; `turn_complete.stop_reason="interrupted"` on the resulting SSE |
| File-write tracking | shipped | `PostToolUse` hooks for Write/Edit (path from input) and Bash (mtime diff) → SSE `file_written`; frontend also debounce-refetches tree after Bash completes (catches `mkdir`, `cp`, solver outputs) |
| Sidebar file tree | shipped | Eager subfolders (`Specification/`, `Case/`, `Mesh/`, `Reports/`, `Geometry/`, `handoffs/`) plus any extras the agent creates; click-to-open right panel; "is-new" dots; toast notifications |
| OpenFOAM dict viewer | shipped | Regex tokenizer (`DictView.jsx`); auto-applied to Case/ and Mesh/ files |
| ParaView bridge | shipped | Singleton subprocess + HTTP bridge on port 8765; verbs partitioned into read (11) / write (27) / exec; `paraview` MCP server |
| ParaView UI integration | shipped | Toolbar launch button; right-click "Load into ParaView" on `.foam` files; 409-conflict toasts; cleaned-orphan toast |
| Geometry upload | shipped | `Geometry/` subfolder, multipart endpoint (5 GiB cap, 12 allowed extensions, collision suffix), composer chip → message contract |
| Assistant-turn rehydration | shipped | `message_segments` table preserves text/thinking/tool ordering; reload reproduces the live chat including sub-agent labels |
| Tests | shipped | 18 basic test files + 7 production roundtrips (opt-in via `RUN_LIVE_SUBAGENT_TESTS=1` and/or ParaView on PATH) |
| Tracing / observability | not done (deliberate) | SDK is opaque from outside the subprocess |
| Tutorial RAG | not done (deferred) | Source-tree exploration via sub-agent + direct Grep/Glob is the substitute |
| Improver UI surfaces | shipped | Per-phase AcceptPanel copy for `improver_experiment` + `improver_phase_advance`; experiment/mesh/phase-advance kickoff plumbing wired |
| post_process UI surfaces | not done | Phase not implemented; no AcceptPanel copy, no kickoff plumbing |

---

## 3. The mental model (read this once)

A user turn = **one** `ClaudeSDKClient` opened, **one** `client.query()`,
**one** walk of `client.receive_response()`, then close. Per-turn objects are
cheap; cross-turn state is not.

The SDK **owns the conversation**. We resume it across turns by passing
`resume=session.sdk_session_id` to `ClaudeAgentOptions`. The local `messages`
+ `message_segments` tables are a **UI mirror** — they reproduce the live chat
on reload (including sub-agent prefixes, tool input/output panels, and
thinking blocks). We **never** replay them back to the LLM.

Adding a new phase is mostly:
1. Fill in the entry in `PHASE_CONFIGS` (model, prompt template, tool list,
   allowed_tools, permission_mode, max_turns, optional subagents/effort/thinking/hooks).
2. Drop a prompt template in `prompts/`.
3. Write a 30–40-line phase handler that loads config, formats the prompt with
   any phase-specific variables, calls `build_tooling()` (with
   `extra_mcp_tools=_SUBAGENT_TOOL_UNION` if it has sub-agents), and yields
   events from `run_turn()`.
4. Wire the handler into `PHASE_HANDLERS` in [src/api/routes.py](../src/api/routes.py).
5. Decide phase-transition mechanism (`request_approval` style ↔
   `/approve-{phase}` endpoint, with or without auto-resume).
6. Frontend updates (per-phase AcceptPanel copy via `pendingKind`, any new
   event types, approve handler).

---

## 4. Folder layout

```
agenticCFD_sdk/
├── src/
│   ├── config.py                    # PHASE_CONFIGS, SUBAGENT_REGISTRY,
│   │                                  GEOMETRY_EXTENSIONS, paths
│   ├── db.py                        # SQLite schema + accessors, slugify()
│   ├── api/
│   │   ├── app.py                   # FastAPI app, lifespan, env-strip
│   │   └── routes.py                # 20 endpoints; SSE event loop
│   ├── agent/
│   │   ├── core.py                  # run_turn(); SDK ↔ StreamEvent translation;
│   │   │                              segment accumulator for DB persistence
│   │   ├── permissions.py           # Future registry: allow / deny /
│   │   │                              deny_with_feedback
│   │   ├── active_runs.py           # Live ClaudeSDKClient registry for /interrupt
│   │   ├── hooks.py                 # PostToolUse → file_written tracker
│   │   └── subagents.py             # build_subagents() → (agents dict, tool union)
│   ├── tools/
│   │   ├── __init__.py              # build_tooling(); _CUSTOM_TOOLS map;
│   │   │                              translate_tool_names()
│   │   ├── present_spec.py          # @tool present_specification (simulation_spec)
│   │   ├── request_approval.py      # @tool request_approval (case_builder)
│   │   ├── request_subtask_approval.py   # @tool (mesh sub-step gate)
│   │   ├── request_experiment_approval.py # @tool (improver experiment-plan gate)
│   │   ├── request_mesh_approval.py  # @tool (improver mid-run mesh gate; reuses mesh_step)
│   │   ├── request_phase_advance.py # @tool (terminal gate; mesh + improver)
│   │   ├── commit_phase_advance.py  # @tool (post-approval handoff commit; all terminal phases)
│   │   └── paraview/
│   │       ├── __init__.py          # PARAVIEW_READ_TOOLS / WRITE_TOOLS / EXEC_TOOL
│   │       ├── _client.py           # HTTP helper bridge_call(path, payload)
│   │       ├── read_paraview_state.py    # 11 @tool read verbs
│   │       ├── change_paraview_state.py  # 27 @tool write verbs
│   │       └── exec_tool.py         # @tool paraview_exec (code|script_path)
│   ├── paraview/
│   │   ├── bridge.py                # Loaded INSIDE ParaView (paraview --script=…);
│   │   │                              never imported from backend code
│   │   └── lifecycle.py             # launch() / is_running() / force_kill;
│   │                                  orphan-bridge recovery on a stale port
│   └── phases/
│       ├── simulation_spec.py          # Phase handler (Sonnet 4.5)
│       ├── case_builder.py          # Phase handler (Sonnet 4.6, sub-agents, cwd=Case/)
│       ├── mesh.py                  # Phase handler (Opus 4.6, sub-agents, cwd=project root)
│       └── improver.py              # Phase handler (Opus 4.6, cfd_general_purpose sub-agent,
│                                      cwd=project root; sub-agents built per-turn)
├── prompts/                         # many historical *_draft.txt alongside the live ones
│   ├── simulation_spec.txt                     # simulation_spec phase
│   ├── case_builder_with_explore_agent.txt  # case_builder phase
│   ├── mesh_agent.txt                       # mesh phase
│   ├── improver_agent_draft.txt             # improver phase (the live one — see config.py)
│   ├── post_process.txt                     # ⚠ referenced by config but MISSING on disk
│   ├── paraview_operator.txt                # sub-agent prompt
│   ├── openFoam2412_repository_explore.txt  # sub-agent prompt
│   └── cfd_general_purpose_draft.txt        # sub-agent prompt (the live one)
├── frontend/                        # React + Vite UI
├── data/                            # SQLite DB (gitignored)
├── projects/                        # Per-project work folders (gitignored)
├── docs/
│   ├── architecture.md                              # Original design doc (stale)
│   └── project_state.md                             # ← this file
├── tests/
│   ├── basic/   (18 files — see §23)
│   ├── production/ (7 roundtrips — opt-in via env)
│   └── openFoam_test_case/   # Shared sample case (difficult_w_fields.foam)
├── main.py                          # uvicorn entrypoint
├── pyproject.toml                   # uv-managed Python deps
└── CLAUDE.md                        # Project conventions
```

---

## 5. Architecture

### 5.1 Process model

```
┌─── React (Vite, :5173) ─────────────────────────────────────────────────┐
│   Sidebar (projects + file tree w/ context menus)                       │
│   ChatColumn (phase pill, ParaView launch button, messages,             │
│               AcceptPanel/PermissionPanel/Composer)                      │
│   FilePanel | SpecPanel (right pane, dict viewer / markdown / binary)    │
└──────────┬──────────────────────────────────────────────────────────────┘
           │ HTTP + SSE + multipart (/api/*)
┌──────────▼──────────────────────────────────────────────────────────────┐
│ FastAPI (uvicorn, :8000)                                                │
│   src/api/routes.py — endpoints + SSE event loop                         │
│           │                                                              │
│           ├── dispatches /messages by project.phase                     │
│           │     ↓                                                       │
│           │   src/phases/{simulation_spec, case_builder, mesh, improver}.py  │
│           │     ↓                                                       │
│           │   src/agent/core.py — run_turn() opens ClaudeSDKClient       │
│           │           │ (one per user turn; resumed by sdk_session_id)   │
│           │           ↓                                                 │
│           │   claude-agent-sdk → spawns `claude` CLI subprocess          │
│           │           │  conversation state + compaction + tool dispatch │
│           │           ↓                                                 │
│           │   HTTPS to Anthropic (Claude Code subscription auth)         │
│           │                                                              │
│           └── /paraview/{launch,load} ──→ src/paraview/lifecycle.py     │
│                                              │                          │
│                                              ▼                          │
│                                       paraview --script=bridge.py        │
│                                       (HTTP bridge on :8765)             │
└──────────┬──────────────────────────────────────────────────────────────┘
           │
   ┌───────▼──────────┐    ┌─────────────────────────────────────────┐
   │ SQLite           │    │ projects/{folder_name}/                  │
   │ data/agenticcfd.db│   │   Specification/                         │
   │ (projects,       │    │   Case/{0, constant, system}/            │
   │  sessions,       │    │   Mesh/                                  │
   │  messages,       │    │   Reports/                               │
   │  message_segments)│   │   Geometry/                              │
   └──────────────────┘    └─────────────────────────────────────────┘
```

### 5.2 One turn, end to end

User types in the composer →

1. **Frontend** POST `/api/projects/{id}/messages` with `{content}`.
2. **API layer** ([routes.py:384](../src/api/routes.py#L384)) loads the project,
   resolves `PHASE_HANDLERS[project.phase]`, gets/creates the current session,
   and persists the user's message to `messages` (UI mirror) **before** opening
   the SSE stream — a dropped connection mid-stream still leaves the input on
   disk. Feedback prefixes (`[Feedback on case]:` / `[Feedback on mesh]:`)
   clear the approval-pending flags here.
3. **Phase handler** loads its config from `PHASE_CONFIGS`, formats the prompt
   template (simulation_spec needs `{expertise_level}`; case_builder needs
   `{simulation_specification}` and `{openfoam_source_dir}`; mesh additionally
   needs `{geometry_dir}` as an absolute path), builds tooling
   (`build_tooling()` → MCP servers + `(tools, allowed_tools, mcp_servers)`),
   and yields events from `run_turn(...)`.
4. **`run_turn()`** ([agent/core.py:314](../src/agent/core.py#L314)) opens
   `ClaudeSDKClient(options=...)` with `resume=session.sdk_session_id`, registers
   the client in `active_runs` (so `/interrupt` can find it), calls
   `client.query(user_message)`, and walks `client.receive_response()` in a
   background task. An `asyncio.Queue` decouples the SDK consumer from the
   outer generator so the `can_use_tool` callback can push permission events
   without fighting for the yield slot.
5. **SDK message types** map onto `StreamEvent`s:
   - `SdkStreamEvent` (token-level) → `text_delta` / `thinking_started` /
     `tool_started`. As text/thinking/tool events fire, a `_SegmentAccumulator`
     mirrors them into the segment list that will be persisted at end of turn.
   - `AssistantMessage` (assembled) → `thinking_text` (atomic) / `tool_input`
     (with full input dict) / `specification_presented` / `approval_requested`
     / `subtask_approval_requested` / `phase_advance_requested`. Sub-agent text
     is **not** stored as the parent's reply (only `parent_tool_use_id is None`
     text feeds the legacy `messages.content` column).
   - `UserMessage` (tool-result wrapper) → `tool_output`
   - `SystemMessage(init)` / `ResultMessage` → capture `session_id`
   - `ResultMessage` → emit `assistant_turn` (internal, carries text +
     segments), `sdk_session_id` (internal), `turn_complete` (with
     `stop_reason="interrupted"` when the user pressed Stop)
6. **API layer** consumes internal events (`sdk_session_id` → `update_session`,
   `assistant_turn` → `save_assistant_turn` writing `messages` + N
   `message_segments` rows); persists side effects of public ones
   (`specification_presented` → `projects.spec_draft`, the three
   approval-requested events → `approval_pending=1` + `approval_kind=…`);
   forwards everything else as SSE.
7. **Frontend** reducer in [useAgentStream.js](../frontend/src/hooks/useAgentStream.js)
   dispatches by event type, building up `messages: Segment[]` per agent
   bubble (segments = `text` | `thinking` | `tool`). Sub-agent activity is
   tagged with the parent_tool_use_id and rendered with an `[<label>]` prefix.

### 5.3 Why an internal queue?

`include_partial_messages=True` enables token-level streaming **and** also
yields the assembled `AssistantMessage`. We use them for non-overlapping
purposes:

- `StreamEvent` → token-level `text_delta` for live UI
- `AssistantMessage` → tool-use input (full input dict needed) and
  thinking blocks; tool-use detectors (`_is_request_approval`,
  `_is_subtask_approval`, `_is_phase_advance`, `_is_commit_phase_advance`,
  `_is_present_spec`) fire here so the API layer can persist the matching
  approval state (or trigger the phase transition)

Don't try to deduplicate; this is intentional.

---

## 6. Configuration: PHASE_CONFIGS

Located in [src/config.py:201](../src/config.py#L201). One entry per phase.

| Key | Type | Purpose |
|---|---|---|
| `model` | `str` | Model ID. Forwarded to `ClaudeAgentOptions.model`. |
| `prompt_template` | `str` | Filename in `prompts/`. |
| `tools` | `list[str]` | What the model **sees** in its tool schema. Built-ins (`Read`, `Write`, `Edit`, `Glob`, `Grep`, `Bash`, `WebSearch`, `WebFetch`, `Agent`) are listed verbatim; custom names map to `mcp__<server>__<name>` via `translate_tool_names()`. |
| `allowed_tools` | `list[str]` | Subset of `tools` that auto-approves. Anything in `tools` but not here routes through `can_use_tool`. |
| `permission_mode` | `str` | Always `"default"` so non-allowlisted tools route to the callback. **Never** `"bypassPermissions"`. |
| `effort` | `"low" \| "medium" \| "high" \| "max" \| None` | None defers to SDK default. |
| `thinking` | `dict \| None` | `{"type": "adaptive"}` is the current pattern; `{"type": "enabled", "budget_tokens": N}` is documented as broken with streaming. |
| `hooks` | `dict[str, list[HookMatcher]] \| None` | Per-phase hooks. The file-write tracker is **always** added on top via `merge_hooks()` in `run_turn`. |
| `max_turns` | `int` | Per-phase loop bound. |
| `subagents` | `list[str] \| None` | Names from `SUBAGENT_REGISTRY`. None disables delegation. |

### Current values

| Phase | Model | Tools (visible / gated) | Sub-agents | effort / thinking | max_turns |
|---|---|---|---|---|---|
| `simulation_spec` | sonnet-4-5 | `present_specification, WebSearch, WebFetch, AskUserQuestion` / `WebFetch` + `AskUserQuestion` gated | — | high / adaptive | 30 |
| `case_builder` | **sonnet-4-6** | `Read, Write, Edit, Glob, Grep, Bash, Agent, WebFetch, request_approval, commit_phase_advance` / `Bash` + `WebFetch` gated | `openfoam2412_repository_explore` | high / adaptive | 60 |
| `mesh` | **opus-4-6** | `Read, Write, Edit, Glob, Grep, Bash, Agent, WebSearch, WebFetch, *PARAVIEW_READ_TOOLS, paraview_exec, request_subtask_approval, request_phase_advance, commit_phase_advance` / `Bash` + `WebFetch` + `paraview_exec` gated | `openfoam2412_repository_explore`, `paraview_operator` | high / adaptive | **200** |
| `improver` | **opus-4-6** | `Read, Write, Edit, Glob, Grep, Bash, Agent, WebSearch, WebFetch, *PARAVIEW_READ_TOOLS, *PARAVIEW_WRITE_TOOLS, paraview_exec, request_experiment_approval, request_mesh_approval, request_phase_advance, commit_phase_advance` / `Bash` + `WebFetch` + `*PARAVIEW_WRITE_TOOLS` + `paraview_exec` gated | `cfd_general_purpose` | high / adaptive | **20000** |
| `post_process` | sonnet-4-5 | `WebSearch, Read, Write, Edit` / same *(stub — no handler; prompt file missing)* | — | — / — | 30 *(stub)* |

### Bash-permission convention

Bash is in `tools` (model sees it) but not in `allowed_tools` for case_builder
and mesh. Every Bash call routes through `can_use_tool` → SSE
`permission_requested` → `PermissionPanel` → user clicks Allow / Deny / Deny
with feedback → POST `/permission/{tool_use_id}` (or `…/deny-feedback`) →
`permissions.resolve_*` → SDK Future resolves → agent unblocks. The basic test
[tests/basic/test_permissions_config.py](../tests/basic/test_permissions_config.py)
asserts no phase ever pre-approves Bash.

`Agent` (the sub-agent invocation tool) **is** auto-approved; the gating
happens on whatever tools the sub-agent itself calls, which re-enter
`can_use_tool` with `agent_id` set so the modal can prefix the sub-agent's
name. The ParaView operator's **write** verbs are not pre-approved in the
mesh phase — each write floats up to the user. The operator's **read** verbs
are pre-approved (they're in mesh's `allowed_tools`).

### `paraview_exec` is gated

`paraview_exec` lets the operator run arbitrary `paraview.simple.*` Python
inside the bridge process. It is NOT in `allowed_tools` — every call surfaces
as a permission prompt, mirroring the Bash policy.

---

## 7. Sub-agent system

### Registry

`SUBAGENT_REGISTRY` in [src/config.py:86](../src/config.py#L86). Single source
of truth. Each entry has:

| Key | Purpose |
|---|---|
| `display_name` | Human label surfaced to UI as a prefix on chat / permission rows. The frontend has its own copy in `SUBAGENT_DISPLAY_NAMES` ([useAgentStream.js:57](../frontend/src/hooks/useAgentStream.js#L57)) keyed by the same name — keep in sync. |
| `description` | Selection hint the parent model reads when deciding whether to delegate. |
| `prompt_template` | File in `prompts/`. Substituted via plain `.replace()` (NOT `.format()`) for `{openfoam_source_dir}` — the orientation block in the explore prompt has literal `{...}` braces. |
| `tools` | Sub-agent's tool list, raw names. `build_subagents()` runs them through `translate_tool_names()` to get the model-facing `mcp__<server>__<name>` form. |
| `model` | Alias (`"haiku"`, `"sonnet"`, `"opus"`, `"inherit"`) or full ID. |
| `effort` | Optional reasoning budget. `AgentDefinition` has no `thinking` field — `effort` is the dial. |

### Materialisation

`build_subagents(names)` in [src/agent/subagents.py](../src/agent/subagents.py)
loads the registry entries listed in a phase's `subagents` key, substitutes
the prompt template, **translates tool names to MCP-prefixed form**, and
returns:

1. `{name: AgentDefinition}` — the dict the SDK expects under
   `ClaudeAgentOptions.agents`.
2. The **MCP tool union** — every custom tool any sub-agent might call. Phase
   handlers pass this to `build_tooling(..., extra_mcp_tools=union)` so the
   MCP servers register every tool the sub-agent needs, even when the parent
   doesn't expose them itself.

Unknown names raise `KeyError` so a typo surfaces at startup.

### Current sub-agents

| Name | Model | Tools | Used by |
|---|---|---|---|
| `openfoam2412_repository_explore` | haiku | `Bash, Read, Glob, Grep` | case_builder, mesh |
| `paraview_operator` | sonnet-4-5 (effort=medium) | `PARAVIEW_READ_TOOLS + PARAVIEW_WRITE_TOOLS + [paraview_exec]` (computed) | mesh |
| `cfd_general_purpose` | **opus-4-6** (effort=high) | `Read, Write, Edit, Glob, Grep, Bash, WebSearch, WebFetch + PARAVIEW_READ/WRITE + paraview_exec` (no `Agent`) | improver |

The operator's `tools` is **computed** from the constants in
`src/tools/paraview/__init__.py` so the registry can't drift from the actual
MCP surface. Adding a new bridge verb flows through automatically.

`cfd_general_purpose` is the improver's only sub-agent — a broad self-contained
worker (research, ParaView setup, source-tree synthesis, iteration-history
reflection). It deliberately has **no `Agent` tool**: the SDK blocks
sub-sub-agent delegation, so the improver's other specialists are unreachable
from inside it. Its prompt bakes in `{project_dir}` (substituted per-turn)
because the parent may `cd` away in Bash calls.

### Tagging in the stream

Streaming events that originate inside a sub-agent invocation carry
`parent_tool_use_id` (the parent's `Agent` tool call ID). The frontend's
reducer captures the `subagent_type` from the parent's `tool_input` for that
ID, then prefixes downstream events with the sub-agent's display name so the
user can tell which agent did what. The map clears at every `turn_complete`.

Permission requests from sub-agents additionally carry `agent_id` so the
permission modal can prefix `[<sub-agent label>] wants to ...`.

---

## 8. Permission gate

### Backend trio (now quartet)

- **Callback** ([core.py:346](../src/agent/core.py#L346)): `can_use_tool` runs
  inside the SDK's loop. It serialises behind `gate_lock` (one prompt at a
  time), creates an `asyncio.Future`, registers it under the SDK-assigned
  `tool_use_id`, emits `permission_requested`, and awaits the Future with a
  600-second timeout. On timeout, returns `PermissionResultDeny`.
- **Registry** ([permissions.py](../src/agent/permissions.py)): module-level
  `dict[str, Future]`. `register` / `unregister` / `resolve_allow` /
  `resolve_deny` / **`resolve_deny_with_feedback`**. Resolvers return `False`
  if the id is unknown or the Future is already resolved (race-safe).
- **HTTP route** ([routes.py:720](../src/api/routes.py#L720)): POST
  `/api/projects/{pid}/permission/{tool_use_id}` with `{"decision": "allow"|"deny"}`.
- **Deny-with-feedback route** ([routes.py:747](../src/api/routes.py#L747)):
  POST `/api/projects/{pid}/permission/{tool_use_id}/deny-feedback` with
  `{"message": "..."}` — denies the call but passes the user's text verbatim
  as the reason. The agent keeps running (`interrupt=False`) and can adjust.

### Frontend trio

- **Event** (`permission_requested`) → reducer stores `permissionRequest`
  with the sub-agent display name when `agent_id` is set.
- **PermissionPanel** ([components/PermissionPanel.jsx](../frontend/src/components/PermissionPanel.jsx))
  swaps in below the chat in place of the composer. Bash gets a dedicated
  rendering with the command + description; other tools fall back to a JSON
  pretty-print. The panel has an Allow button, a Deny button, and a
  "Deny with feedback" textarea that POSTs to the deny-feedback endpoint.
- **Resolve** → `submitPermission("allow"|"deny")` or
  `submitPermissionDenyFeedback(message)` POSTs the decision and dispatches
  `permission_resolved` with the captured `tool_use_id` so a parallel-call
  race doesn't wipe a follow-up prompt.

### Deny semantics

`permissions.DENY_MESSAGE` is the canned string the SDK passes back to the
agent on a plain deny: "User denied this action. Don't retry the same
command, try a different approach." The deny-with-feedback path replaces this
string with the user's own message.

---

## 9. Turn interrupts

The user can stop an in-flight turn from the UI. Backend mechanism:

- **`active_runs`** ([src/agent/active_runs.py](../src/agent/active_runs.py))
  is a module-level `dict[project_id, _ActiveRun]`. `run_turn()` registers the
  `ClaudeSDKClient` here on entry and unregisters on exit. Each `_ActiveRun`
  also carries an `interrupted: bool` flag.
- **`/interrupt`** ([routes.py:770](../src/api/routes.py#L770)) calls
  `active_runs.request_interrupt(project_id)`, which sets the flag **before**
  awaiting `client.interrupt()` so a fast-arriving terminal `ResultMessage`
  can't race the consumer's interrupt check.
- **In `consume_sdk`** ([core.py:591](../src/agent/core.py#L591)): when the
  terminal `ResultMessage` arrives with `is_error=True`, the consumer checks
  `active_runs.was_interrupted(project_id)`. Interrupted turns are NOT emitted
  as `error` events; the consumer emits `turn_complete` with
  `stop_reason="interrupted"` and lets partial text/segments persist normally.

The SDK itself inserts a `[Request interrupted by user]` marker into the
session transcript, so the next resumed turn sees the interrupt without any
extra plumbing from us.

Frontend (`useAgentStream.js#interrupt`): POSTs `/interrupt` and lets the
backend wrap the SSE up. Does **not** abort the SSE locally — that would
race the backend persistence path. The reducer tags the partial agent
message with `interrupted: true` on `turn_complete` so the row can render
an "(interrupted)" chip.

---

## 10. File-write tracker

Always-on `PostToolUse` hook factory in [src/agent/hooks.py](../src/agent/hooks.py).
Mounted by `run_turn()` for **every** phase (merged with any phase-supplied
hooks via `merge_hooks()`). Two matchers:

- **`Write|Edit`** — file path comes straight from `tool_input.file_path`.
  Resolved against `cwd` (defaulted to `project_dir`); writes outside the
  project root are silently ignored.
- **`Bash`** — no path in input. Walks `project_dir`, diffs against an
  in-process `{rel_path: mtime_ns}` snapshot seeded at hook construction. Any
  new or modified file fires. Snapshot refreshes wholesale after each Bash.

Each matched write enqueues `{name, path, type, subfolder}` (where
`subfolder` is the first path segment — `Specification`, `Case`, `Mesh`,
`Reports`, `Geometry`, `handoffs`). The queue is drained between SDK message
yields in `run_turn()`, producing `file_written` SSE events.

Frontend has two complementary mechanisms:
- `App.handleFileWritten` enqueues a toast, marks the file as new
  (per-tab `Map<projectId, Set<path>>`), and merges into the local file tree.
- The reducer additionally tracks every `tool_started` whose tool is `Bash`
  and schedules a **debounced (150 ms) refetch** of the project file tree
  when the matching `tool_output` arrives. This catches `mkdir`, `cp`, `rm`,
  and program outputs like `blockMesh` populating `constant/polyMesh/` — none
  of which fire the Write/Edit hook and may not all be visible via mtime
  diff if they happen between two SDK message iterations.

---

## 11. Phase handlers

All four handlers follow the same shape — load config, format prompt, build
tooling (with `extra_mcp_tools=_SUBAGENT_TOOL_UNION` when sub-agents are
declared), yield from `run_turn()`. Differences:

### `simulation_spec` ([src/phases/simulation_spec.py](../src/phases/simulation_spec.py))

- Prompt formatted with `{expertise_level}`.
- No `cwd` override (defaults to `project_dir`).
- Tools: `present_specification`, `WebSearch`, `WebFetch` (last is gated).
- No sub-agents.

### `case_builder` ([src/phases/case_builder.py](../src/phases/case_builder.py))

- Prompt formatted with `{simulation_specification}` (read from disk —
  `Specification/simulation_specification.md`, written by `/approve-spec`) and
  `{openfoam_source_dir}` (constant).
- `cwd=project_dir/Case/` so relative paths in `Write`/`Edit`/`Bash` land
  inside the case directory.
- `project_dir` stays at the project root so the file-write hook classifies
  by first segment.
- Tools: `Read, Write, Edit, Glob, Grep, Bash, Agent, WebFetch, request_approval, commit_phase_advance`.
  Bash and WebFetch are gated. `commit_phase_advance` is only legal to call
  during the post-approval handoff turn (see §13 pattern B).
- Sub-agent: `openfoam2412_repository_explore`.

### `mesh` ([src/phases/mesh.py](../src/phases/mesh.py))

- Prompt formatted with `{simulation_specification}` (same source as
  case_builder), `{openfoam_source_dir}`, and `{geometry_dir}` (absolute
  path to `Geometry/`).
- **`cwd=project_dir`** (NOT `Case/` or `Mesh/`). Different from case_builder.
  Relative paths in the prompt land at `Case/system/blockMeshDict`,
  `Specification/simulation_specification.md`, `Geometry/<file>`. The
  `{geometry_dir}` placeholder gives the agent the absolute path so it can
  pass it to ParaView verbs (which resolve against `PV_PROJECT_ROOT`, set by
  `lifecycle.launch()`).
- Tools: `Read, Write, Edit, Glob, Grep, Bash, Agent, WebSearch, WebFetch,
  *PARAVIEW_READ_TOOLS, paraview_exec, request_subtask_approval,
  request_phase_advance, commit_phase_advance`. Bash, WebFetch, and paraview_exec
  are gated. `commit_phase_advance` is only legal to call during the
  post-approval handoff turn (see §13 pattern D).
- Sub-agents: `openfoam2412_repository_explore`, `paraview_operator`.

### `improver` ([src/phases/improver.py](../src/phases/improver.py))

- Prompt formatted with `{simulation_specification}` (read from
  `Specification/simulation_specification.md`), `{project_dir}` (absolute), and
  `{openfoam_source_dir}`.
- **`cwd=project_dir`** (same as mesh).
- Tools: `Read, Write, Edit, Glob, Grep, Bash, Agent, WebSearch, WebFetch,
  *PARAVIEW_READ_TOOLS, *PARAVIEW_WRITE_TOOLS, paraview_exec,
  request_experiment_approval, request_mesh_approval, request_phase_advance,
  commit_phase_advance`. Bash, WebFetch, the ParaView **write** verbs, and
  paraview_exec are gated. **Unlike mesh, the improver parent exposes the
  ParaView write verbs directly** (still gated) in addition to delegating —
  it has no `paraview_operator`, only `cfd_general_purpose`.
- Sub-agent: `cfd_general_purpose` (built **per-turn** inside the handler, not
  at module scope, so `{project_dir}` is baked into its prompt fresh each turn).
- `max_turns=20000` — effectively unbounded; an improver run is a long
  multi-experiment loop, not a single bounded edit.

---

## 12. SSE event vocabulary

### Forwarded to the frontend

| Event | Payload | Meaning |
|---|---|---|
| `thinking_started` | `{parent_tool_use_id}` | Reasoning began. |
| `thinking_text` | `{content, parent_tool_use_id}` | Assembled reasoning text — pairs with the most recent `thinking_started` in the same scope. |
| `text_delta` | `{content, parent_tool_use_id}` | Response token. |
| `tool_started` | `{tool, id, parent_tool_use_id}` | Tool call began (bare tool name + id; full input arrives in `tool_input`). |
| `tool_input` | `{id, tool, input, parent_tool_use_id}` | Assembled tool input dict. |
| `tool_output` | `{tool_use_id, content, is_error, parent_tool_use_id}` | Tool result; `tool_use_id` matches an earlier `tool_started.id`. |
| `specification_presented` | `{markdown}` | `present_specification` was invoked. Backend persists `projects.spec_draft`. |
| `approval_requested` | `{}` | `request_approval` was invoked (case_builder). Backend sets `approval_pending=1, approval_kind="case"`. |
| `subtask_approval_requested` | `{}` | `request_subtask_approval` (mesh) **or** `request_mesh_approval` (improver) was invoked — the two tools share this one event. Backend sets `approval_pending=1, approval_kind="mesh_step"`. |
| `experiment_approval_requested` | `{}` | `request_experiment_approval` was invoked (improver). Backend sets `approval_pending=1, approval_kind="improver_experiment"`. |
| `phase_advance_requested` | `{}` | `request_phase_advance` was invoked (terminal; mesh **and** improver). Backend sets `approval_pending=1` and a **phase-scoped** `approval_kind` (`mesh_phase_advance` or `improver_phase_advance`) computed by `_approval_kind_for()`. |
| `file_written` | `{name, path, type, subfolder}` | Write/Edit/Bash landed inside the project. |
| `permission_requested` | `{tool_use_id, tool, input, agent_id}` | Awaiting Allow/Deny POST back. `agent_id` set when the call originated inside a sub-agent. |
| `question_requested` | `{tool_use_id, questions}` | The built-in `AskUserQuestion` tool was invoked (simulation_spec). Awaiting a POST to `/question/{tool_use_id}/answer`. |
| `compaction_started` | `{trigger}` | `PreCompact` hook fired — the CLI is compacting context. UI shows a transient spinner. |
| `compaction_complete` | `{trigger, pre_tokens, post_tokens}` | SDK `compact_boundary` SystemMessage arrived. Backend persists a `role="compaction"` message row (so the divider survives reload); frontend renders a `CompactionDivider`. |
| `spec_approved` | `{phase_from, phase_to, transitioned_at}` | Emitted by `/approve-spec` SSE before the case_builder kickoff. |
| `case_approved` | `{status, phase_from, phase_to}` | Emitted by `/approve-case` SSE up front, before the case_builder's handoff turn. Phase pill does NOT flip yet — that waits for `phase_transitioned`. |
| `mesh_step_approved` | `{status, auto_resumed}` | Emitted by `/approve-mesh-step` SSE before the agent resumes. Shared by the mesh phase and the improver's mid-run mesh approval. |
| `mesh_phase_approved` | `{status, phase_from, phase_to}` | Emitted by `/approve-mesh-phase-advance` SSE up front, before the mesh agent's handoff turn. Phase pill does NOT flip yet — that waits for `phase_transitioned`. |
| `experiment_approval_approved` | `{status, auto_resumed}` | Emitted by `/approve-experiment` SSE before the improver resumes its experiment run. |
| `improver_phase_approved` | `{status, phase_from, phase_to}` | Emitted by `/approve-improver-phase-advance` SSE up front, before the improver's handoff turn. Phase pill waits for `phase_transitioned`. |
| `phase_transitioned` | `{phase_from, phase_to, transitioned_at, auto_advanced?, downstream_agent_starting?}` | Emitted after the outgoing agent calls `commit_phase_advance` (or the route's safety net auto-advances). This is when the phase pill + badge + transition divider actually land. `auto_advanced=true` only when the safety net fired. `downstream_agent_starting=true` when a kickoff turn follows on the same stream (case→mesh, mesh→improver); `false` for improver→post_process (no handler yet). |
| `turn_complete` | `{stop_reason}` | End of turn. `stop_reason="interrupted"` when the user pressed Stop. Clears sub-agent label map. |
| `error` | `{message, recoverable}` | Failure. Suppressed for user-initiated interrupts. |
| `status` | `{message}` | Reserved; not currently emitted. |

### Internal (consumed by the API layer, never sent to client)

| Event | Effect |
|---|---|
| `sdk_session_id` | `sessions.sdk_session_id` updated. |
| `assistant_turn` | `messages` row + N `message_segments` rows inserted (role=assistant). Carries `{text, segments}` — `text` for the legacy content column, `segments` for the ordered breakdown. |
| `phase_advance_committed` | Agent called `commit_phase_advance` during the post-approval handoff turn. Route layer flips `projects.phase`, creates the next session, and (for case_builder→mesh) starts the downstream kickoff turn on the same SSE stream. Surfaced to the frontend as `phase_transitioned`. |

---

## 13. Approval / phase-transition patterns

Several patterns live in the codebase. All go through an explicit user
gesture. The two-step terminal transitions (B, D, F) have a safety-net
auto-advance if the agent forgets to call `commit_phase_advance`. A separate
**question gate** (`AskUserQuestion`, pattern H) is not an approval but rides
the same `can_use_tool` Future machinery.

### Pattern A — `present_specification` (simulation_spec)

1. Agent calls the `present_specification` MCP tool with the markdown as the
   only argument.
2. `core.py` detects the `ToolUseBlock` by name in the assembled
   `AssistantMessage`, emits `specification_presented`.
3. API layer persists `projects.spec_draft`.
4. Frontend opens `SpecPanel` (right pane) + `AcceptPanel` (chat footer).
5. User picks Yes / Feedback / Question. Yes → POST `/approve-spec` (SSE) →
   `spec_approved` event up front, then the case_builder kickoff turn streams
   on the same connection.
6. `/approve-spec` writes `Specification/simulation_specification.md`, creates a
   `case_builder` session, advances `projects.phase`. The backend-owned
   kickoff prompt is **not** persisted as a user message.

### Pattern B — `request_approval` (case_builder → mesh, two-step)

1. Agent calls the `request_approval` MCP tool (no arguments).
2. `core.py` emits `approval_requested`; API layer flips
   `projects.approval_pending=1, approval_kind="case"`.
3. Frontend opens `AcceptPanel` with case_builder copy. User picks:
   - **Yes** → POST `/approve-case` (**SSE**). The route:
     a. Streams `case_approved` up front (reducer clears the pill but
        does NOT flip the phase pill yet — handoff turn is about to
        run).
     b. Resumes the existing case_builder SDK session with the
        backend-owned trigger `"User approved the case. Proceed with
        the handoff."` (NOT persisted as a user message).
     c. Agent writes `handoffs/case_builder.md` and calls
        `commit_phase_advance`. The agent layer emits
        `phase_advance_committed` (internal) — the route catches it,
        does the DB transition, and yields `phase_transitioned`
        (reducer flips the phase pill, drops the approval badge +
        phase-transition divider).
     d. Drains the rest of the case_builder turn until `turn_complete`.
     e. Starts the mesh kickoff turn on the SAME SSE stream with the
        backend-owned `_MESH_KICKOFF` prompt (NOT persisted).
     f. Stream closes when the mesh turn's `turn_complete` fires.
   - **Feedback** → message prefixed with `[Feedback on case]: ` (the
     backend clears `approval_pending` + `approval_kind` on receipt).
     Do NOT pre-write the handoff before approval.
   - **Ask a question** → AcceptPanel dismisses; `ApprovalPendingPill`
     appears above the composer with a one-click `Approve` button.
4. Refresh survival: `GET /projects/{id}` returns `approval_pending` and
   `approval_kind`; reducer rehydrates the AcceptPanel.

**Safety net**: if the case_builder's handoff turn ends without ever
calling `commit_phase_advance` (agent forgot, errored, hit `max_turns`),
the route auto-advances anyway and tags the `phase_transitioned` event
with `auto_advanced=true`. The handoff file may be absent in that case.

### Pattern C — `request_subtask_approval` (mesh sub-steps)

1. Agent calls `request_subtask_approval` (no args).
2. `core.py` emits `subtask_approval_requested`; API layer flips
   `approval_pending=1, approval_kind="mesh_step"`.
3. Frontend opens `AcceptPanel` with mesh-sub-step copy. User picks:
   - **Yes** → POST `/approve-mesh-step` (SSE) → `mesh_step_approved` event
     up front, then the mesh agent **auto-resumes on the same connection**
     with a backend-owned `"User approved the mesh sub-step. Proceed."`
     prompt (NOT persisted as a user message).
   - **Feedback** → `[Feedback on mesh]: …` prefix; clears approval flags.
   - **Ask a question** → pill.

### Pattern D — `request_phase_advance` (mesh → improver, two-step)

1. Agent calls `request_phase_advance` (no args).
2. `core.py` emits `phase_advance_requested`; API layer flips
   `approval_pending=1, approval_kind="mesh_phase_advance"`.
3. Frontend opens `AcceptPanel` with terminal copy. User picks:
   - **Yes** → POST `/approve-mesh-phase-advance` (**SSE**). Same shape
     as pattern B's `/approve-case`, with these differences:
     - Up-front event is `mesh_phase_approved` (not `case_approved`).
     - Trigger message is `_MESH_HANDOFF_TRIGGER` (`[Approval on mesh]: …
       Proceed with the handoff.`).
     - Handoff path is `handoffs/mesh_agent.md`.
     - **Downstream kickoff turn** — now that improver is built, the route
       transitions the DB, emits `phase_transitioned`
       (`downstream_agent_starting=true`), then streams the improver's
       first turn on the same SSE with `_IMPROVER_KICKOFF`
       (`"Proceed with your task."`).
   - **Feedback** → same `[Feedback on mesh]: …` prefix as Pattern C.

The mesh prefix is **phase-scoped**: `[Feedback on mesh]:` is a no-op in
case_builder and vice versa. Tests pin this.

**Safety net**: same as Pattern B — auto-advance with
`auto_advanced=true` if the mesh handoff turn ends without
`commit_phase_advance`.

### Pattern E — `request_experiment_approval` (improver experiment plans)

A non-terminal gate, shaped like Pattern C. The improver calls
`request_experiment_approval` (no args) before spending compute on an
experiment. `core.py` emits `experiment_approval_requested`; API sets
`approval_kind="improver_experiment"`. On **Yes** → POST `/approve-experiment`
(SSE) → `experiment_approval_approved` up front, then the improver auto-resumes
on the same connection with `_IMPROVER_EXPERIMENT_KICKOFF` (`"User approved the
experiment plan. Proceed."`). Feedback → `[Feedback on …]` prefix; clears flags.

### Pattern F — `request_mesh_approval` (improver mid-run mesh changes)

When an experiment changes the mesh, the improver calls `request_mesh_approval`
before re-running the solver. This **reuses the mesh-step machinery wholesale**:
it emits the same `subtask_approval_requested` event, sets the same
`approval_kind="mesh_step"`, and is approved through the same
`/approve-mesh-step` route (auto-resume, no phase change). The frontend can't
tell it apart from a mesh-phase sub-step — by design.

### Pattern G — `request_phase_advance` (improver → post_process, two-step)

Same machinery as Pattern D, terminal. `approval_kind` resolves to
`improver_phase_advance` (phase-scoped via `_approval_kind_for()`). **Yes** →
POST `/approve-improver-phase-advance` (SSE): `improver_phase_approved` up
front, then the improver handoff turn (trigger `_IMPROVER_HANDOFF_TRIGGER`,
writes `handoffs/improver_agent.md`, calls `commit_phase_advance`), then
`phase_transitioned` to `post_process` with `downstream_agent_starting=false`
— **no kickoff turn** because post_process has no handler yet. Same safety-net
auto-advance as Patterns B/D.

### Pattern H — `AskUserQuestion` (simulation_spec question gate)

Not an approval. The simulation_spec agent calls the built-in `AskUserQuestion`
tool (it's in `tools` but **not** `allowed_tools`, so it routes through
`can_use_tool`). `core.py` emits `question_requested` with the questions array;
the frontend swaps in `QuestionPanel` (a tabbed multi/single-select wizard with
an "Other" free-text path). The user's answers POST to
`/question/{tool_use_id}/answer`, which resolves the tool's Future with an
`allow` + `updated_input` carrying the answers map (or, on timeout, an empty
map plus a freeform `response`). The agent then continues with the answers in
hand.

### About the handoff documents

`handoffs/<phase>.md` is an **agent-to-agent** note, never user-facing
during approval. Its purpose is to convey what the outgoing agent learned
that the incoming agent couldn't recover from reading the project files
alone — decisions, assumptions, useful reference material (paths/links,
not pasted verbatim). The "Handoff to the next agent" section in each
phase's system prompt frames the rules:

- Be short and precise; do not restate file contents.
- Share insights, not instructions — do not prescribe how the
  downstream agent should do its work.
- Pre-writing the handoff before approval is wrong; on a
  `[Feedback on <phase>]:` rejection, address the feedback and call
  `request_*` again.

The handoff file is also what the downstream agent reads on its first
turn — the backend-owned kickoff (`_MESH_KICKOFF`, future
`_IMPROVER_KICKOFF`) points the new agent at it explicitly.

### approval_kind is the durable discriminator

The frontend's `pendingKind` mirrors `projects.approval_kind` exactly; the
AcceptPanel copy and the pill's approve handler both pivot on it. When you add
a new approval-style tool, extend `_APPROVAL_KINDS` in
[routes.py:71](../src/api/routes.py#L71) **and** the matching reducer cases
in [useAgentStream.js](../frontend/src/hooks/useAgentStream.js) rather than
splitting routes by path.

---

## 14. ParaView integration

Phase-3-and-onwards visualisation surface. The frontend gets a live ParaView
window for inspecting meshes, fields, and geometry; the agent gets read + write
access through an HTTP bridge.

### Lifecycle

[src/paraview/lifecycle.py](../src/paraview/lifecycle.py) owns one module-level
slot: the single ParaView subprocess. `launch()` spawns
`paraview --script=bridge.py` with `start_new_session=True` (so a later
group-kill catches `paraview-real` behind the wrapper) and polls
`http://127.0.0.1:8765/ping` until the bridge responds. A second `launch()`
while the first instance is alive raises `ParaviewAlreadyRunningError`. The
frontend never auto-kills a live instance — closing it is the user's gesture.

**Orphan recovery**: if a previous backend died without killing ParaView, the
bridge keeps running and holds port 8765 even though `_record` is empty.
`launch()` probes `/ping` before spawning; if something answers while
`_record is None` it `SIGKILL`s the orphan's process group and surfaces
`cleaned_orphan: True` in the launch response.

### Bridge

[src/paraview/bridge.py](../src/paraview/bridge.py) — loaded **inside ParaView**
via `paraview --script=…`. It imports `vtkmodules` at module top and spawns the
HTTP server as an import side-effect; both fail outside ParaView's interpreter.
**Never import this from backend code.** Use `Path(__file__).parent /
"bridge.py"` if you need the path (lifecycle does).

Relative paths the agent passes to bridge verbs resolve against `PV_PROJECT_ROOT`
(set by `lifecycle.launch()` to `project_dir`), not against `__file__`.

### MCP server

[src/tools/paraview/](../src/tools/paraview/) — every bridge verb is a `@tool`-
decorated SDK MCP tool living on the `paraview` server. Three flavours,
partitioned by file:

- [read_paraview_state.py](../src/tools/paraview/read_paraview_state.py) — 11
  read verbs (get_pipeline, get_source_info, get_camera, save_screenshot, …)
  exported as `PARAVIEW_READ_TOOLS`.
- [change_paraview_state.py](../src/tools/paraview/change_paraview_state.py) —
  27 write verbs (apply_filter, delete_source, set_active, change_color_by,
  set_camera, …) exported as `PARAVIEW_WRITE_TOOLS`.
- [exec_tool.py](../src/tools/paraview/exec_tool.py) — `paraview_exec`
  (separate; accepts `code` XOR `script_path`; bound names inside the exec
  namespace: `paraview.simple.*`, `servermanager`, `vtk`).

The phase config composes its ParaView tool surface from these constants — the
mesh phase exposes reads + exec but **not** writes (writes happen through the
`paraview_operator` sub-agent so the parent doesn't see 27 mutation verbs in
its schema). The **improver** phase differs: it exposes reads + writes + exec
**directly** on the parent (writes and exec gated), since its only sub-agent is
`cfd_general_purpose` (general-purpose, not a ParaView specialist).
`export_snapshot` is intentionally NOT exposed to the agent (a
defensive test guards this — see
[tests/basic/test_paraview_tools_layout.py](../tests/basic/test_paraview_tools_layout.py)).

### HTTP integration

- `POST /api/projects/{id}/paraview/launch` — spawns ParaView. 409 with
  `{message, running_for_project}` on conflict so the frontend can tell the
  user which window to close.
- `POST /api/projects/{id}/paraview/load` — loads a `.foam` (or other dataset)
  into the live bridge. 409 if no instance is running — the frontend's
  right-click handler falls through to launch.

### Sub-agent

The `paraview_operator` sub-agent (see §7) is the recommended path for
multi-step scene mutations from the mesh agent. The parent calls
read verbs directly (`get_pipeline`, etc.) for orientation; anything that
takes more than 2–3 tool calls — apply a slice, set a colour map, move the
camera — gets delegated.

---

## 15. Geometry uploads

`Geometry/` is one of the five eagerly-materialised subfolders. The user can
upload mesh/CAD files via the composer's attach button (chip rendered above
the textarea). Backend:

- `POST /api/projects/{id}/geometry` — multipart endpoint. Validates extension
  against `GEOMETRY_EXTENSIONS` (12 entries: `.stl, .obj, .ply, .vtk, .nas,
  .ftr, .off, .x3d, .step, .stp, .iges, .igs`). Sanitises filename
  (`Path(name).name` + leading-dot strip), resolves collisions with `_1`,
  `_2`, … (caps at 1000). Stream-writes in 1 MiB chunks; partial file is
  unlinked on size-cap overflow (5 GiB cap via `MAX_GEOMETRY_SIZE_BYTES`)
  or any other failure.
- `GET /api/projects/{id}/file` returns `{is_binary, content, size}` — binary
  geometries serve `content: null, is_binary: true` and FilePanel renders a
  "Binary geometry file · &lt;size&gt;" placeholder.

### Chip → message contract

The composer's chips are visual only — picking a file commits it to disk
immediately, but clicking the X on a chip just removes the visual chip (file
stays on disk by design). `buildMessage(text, chips)` produces three message
shapes the mesh agent is taught to recognise:

- text only → `<text>`
- text + chips → `<text>\n\n[Geometry attached: a.stl, b.stl]`
- chips only → `User uploaded geometry: a.stl, b.stl`

Locked in via [Composer.test.js](../frontend/src/components/Composer.test.js).

---

## 16. Database schema

Four tables; defined in [src/db.py:54](../src/db.py#L54).

```sql
projects (
    id TEXT PRIMARY KEY,                                -- uuid
    name TEXT NOT NULL,                                 -- user-facing
    folder_name TEXT NOT NULL UNIQUE,                   -- slugify(name)
    phase TEXT DEFAULT 'simulation_spec',
    expertise_level TEXT DEFAULT 'intermediate',
    spec_draft TEXT,                                    -- latest markdown awaiting approval
    approval_pending INTEGER DEFAULT 0,
    approval_kind TEXT,                                 -- "case" | "mesh_step" | "mesh_phase_advance" |
                                                        --   "improver_experiment" | "improver_phase_advance" | NULL
    status TEXT DEFAULT 'active',
    created_at, updated_at
)

sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,                           -- FK with cascade
    phase TEXT NOT NULL,
    sdk_session_id TEXT,                                -- SDK resume key, NULL until first turn
    created_at
)

messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,                           -- FK with cascade
    role TEXT NOT NULL,                                 -- 'user' | 'assistant' | 'compaction'
    content TEXT NOT NULL,                              -- plain text (legacy); JSON blob for 'compaction' rows
    created_at
)

message_segments (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,                           -- FK with cascade
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,                                 -- 'text' | 'thinking' | 'tool'
    content TEXT,                                       -- text content / tool output
    tool_use_id TEXT,                                   -- (tool only)
    tool_name TEXT,                                     -- (tool only)
    tool_input TEXT,                                    -- JSON-serialised (tool only)
    tool_is_error INTEGER,                              -- (tool only)
    parent_tool_use_id TEXT                             -- sub-agent attribution
)
```

`get_full_chat_history(project_id)` flattens messages across sessions, attaches
`segments` to each assistant entry, inserts `phase_transition` markers between
sessions of different phases, and turns each `role="compaction"` row into a
`{"type": "compaction", ...}` divider entry (malformed JSON degrades to a bare
divider). This is what the frontend reads on page
load to rehydrate the chat — assistant rows with segments rebuild full
text/thinking/tool ordering and sub-agent labels.

`init_db()` is idempotent and includes a migration helper (`_ensure_column`)
for columns added after initial release (`approval_pending`, `approval_kind`).

---

## 17. HTTP endpoints

Defined in [src/api/routes.py](../src/api/routes.py). All under `/api`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/projects` | Create project. Materialises `projects/{folder}/{Specification, Case, Mesh, Reports, Geometry, handoffs}/`. |
| GET | `/projects` | List projects (most-recently-updated first). |
| GET | `/projects/{id}` | Detail + full chat history (incl. segments) + spec_draft + approval state. |
| GET | `/projects/{id}/files` | Walk `projects/{folder}/`, return tree keyed by subfolder (blessed first, ad-hoc folders after). |
| GET | `/projects/{id}/file?path=...` | Read a single file. Returns `{name, path, type, size, is_binary, content}`. Path traversal guarded. |
| POST | `/projects/{id}/geometry` | Upload geometry. Multipart. |
| DELETE | `/projects/{id}` | Filesystem first, then DB cascade. |
| POST | `/projects/{id}/messages` | Send user message; **SSE** stream of phase-handler events. |
| POST | `/projects/{id}/approve-spec` | Write spec to disk, advance phase, **SSE** stream of `spec_approved` + case_builder kickoff turn. |
| POST | `/projects/{id}/approve-case` | **SSE**. Streams `case_approved`, runs the case_builder handoff turn, emits `phase_transitioned`, then streams the mesh kickoff turn on the same connection. |
| POST | `/projects/{id}/approve-mesh-step` | Clear sub-step approval and **SSE** stream of `mesh_step_approved` + auto-resumed agent turn. Shared by mesh sub-steps and the improver's mid-run mesh approval. |
| POST | `/projects/{id}/approve-experiment` | **SSE**. Streams `experiment_approval_approved` + auto-resumed improver turn (no phase change). |
| POST | `/projects/{id}/approve-mesh-phase-advance` | **SSE**. Streams `mesh_phase_approved`, runs the mesh handoff turn, emits `phase_transitioned`, then streams the improver kickoff turn on the same connection. |
| POST | `/projects/{id}/approve-improver-phase-advance` | **SSE**. Streams `improver_phase_approved`, runs the improver handoff turn, emits `phase_transitioned` to `post_process`. No downstream kickoff (post_process not built). |
| POST | `/projects/{id}/permission/{tool_use_id}` | Resolve a `can_use_tool` request. JSON `{decision: allow\|deny}`. |
| POST | `/projects/{id}/permission/{tool_use_id}/deny-feedback` | Deny with user's text as reason. JSON `{message: …}`. |
| POST | `/projects/{id}/question/{tool_use_id}/answer` | Resolve an `AskUserQuestion` gate. JSON `{answers, response?}`. |
| POST | `/projects/{id}/interrupt` | Interrupt the current turn. Plain JSON. Returns `{interrupted: bool}`. |
| POST | `/projects/{id}/paraview/launch` | Spawn ParaView. 409 with running-project info on conflict. |
| POST | `/projects/{id}/paraview/load` | Load a `.foam` into the live bridge. 409 if no instance. |

`PHASE_HANDLERS` ([routes.py:44](../src/api/routes.py#L44)) currently dispatches
to `simulation_spec`, `case_builder`, `mesh`, and `improver`. Sending a message to
a project in `post_process` returns HTTP 400 (no handler yet).

---

## 18. Frontend overview

React + Vite, single-page. State management is reducer-based; one stream hook
per project.

### Layout

`App.jsx` owns the grid: `Sidebar | ChatColumn | (resize handle | right
panel)`. Right panel is either `FilePanel` (a file picked from the tree) or
`SpecPanel` (live spec markdown during simulation_spec review). FilePanel wins
over SpecPanel.

### Components

| File | Role |
|---|---|
| `App.jsx` | Top-level state, project CRUD, file-tree merging, toast wiring, geometry upload routing. |
| `hooks/useAgentStream.js` | The reducer + SSE pump. Owns: messages, streaming flag, **compacting** flag, phase, specDraft, acceptMode, pendingUserAction, approvalPending, **pendingKind**, permissionRequest, **questionRequest**, subagentLabels. Exposes `sendMessage`, `submitFeedback`, `approveSpec`, `approveCase`, `approveMeshStep`, **`approveExperiment`**, `approvePhaseAdvance` (endpoint chosen by `pendingKind`), `submitPermission`, `submitPermissionDenyFeedback`, **`submitQuestionAnswers`**, `interrupt`. `pendingKind` ∈ `case \| mesh_step \| mesh_phase_advance \| improver_experiment \| improver_phase_advance`. `SUBAGENT_DISPLAY_NAMES` now also maps `cfd_general_purpose`. |
| `hooks/useToastQueue.js` | Toast queue (cap 4 visible, FIFO overflow, 2.5s display). Shared between file-written toasts and ParaView toasts. |
| `Sidebar.jsx` | Project list + collapsible nested file tree per project. Right-click context menu on rows (delete project; "Load into ParaView" on `.foam` files). |
| `ChatColumn.jsx` | Phase pill + ParaView launch button + scrolling chat + QuestionPanel/PermissionPanel/AcceptPanel/Composer dispatch. AcceptPanel copy (`ACCEPT_COPY`) and the approve handler are both keyed by `pendingKind` (incl. the two `improver_*` kinds). Footer precedence: QuestionPanel → PermissionPanel → AcceptPanel → Composer (+ ApprovalPendingPill). |
| `QuestionPanel.jsx` | Tabbed wizard that replaces the composer on an `AskUserQuestion` gate. Single/multi-select options + an "Other" free-text path; POSTs answers to `/question/{id}/answer`. |
| `CompactionDivider.jsx` | Persisted in-chat divider marking a context compaction (`pre → post` token counts). Mirrors `PhaseDivider` layout. A transient spinner row shows in `ChatColumn` while `compacting`. |
| `AgentMessage.jsx` | Renders `segments[]` (text/thinking/tool) for an agent bubble. Sub-agent prefix on segment labels. |
| `UserBubble.jsx` | User-message rendering, with user-action prefix stripped on display. |
| `ExpandableEvent.jsx` | Reasoning / tool rows — collapsed by default with input/output panes. |
| `Markdown.jsx` | react-markdown + GFM + KaTeX. Used for spec preview and `.md` files. **No `rehype-raw`** — HTML is stripped. |
| `DictView.jsx` | Regex tokenizer for OpenFOAM dicts. Auto-applied to Case/ and Mesh/ files in `FilePanel`. |
| `FilePanel.jsx` | Right-pane file viewer; routes `.md` → Markdown, Case/Mesh → DictView, binaries → size placeholder, else `<pre>`. Header right-click on `.foam` files surfaces the "Load into ParaView" menu. |
| `SpecPanel.jsx` / `SpecResizeHandle.jsx` | Right-pane spec preview + resize handle during simulation_spec review. |
| `AcceptPanel.jsx` | Yes/Feedback/Question footer; copy + approve handler chosen by `pendingKind`. |
| `ApprovalPendingPill.jsx` | Slim bar above composer in approval-pending state with a one-click Approve. Used by both case_builder and mesh. |
| `PermissionPanel.jsx` | Replaces the composer when the agent is paused on a tool permission request. Bash gets a dedicated rendering. Has Allow / Deny / Deny-with-feedback paths. |
| `Composer.jsx` | The text input + geometry attach button. Disabled while streaming. |
| `ParaviewLaunchButton.jsx` | Toolbar button next to phase pill; single transient loading state. |
| `ConfirmDialog.jsx` / `ContextMenu.jsx` | Reusable dialog and right-click menu primitives. |
| `ToastStack.jsx` / `Toast.jsx` | Top-left of chat column; `file_written` and ParaView toasts surface here. |
| `PhaseDivider.jsx` | Visual divider between phases inside the chat scroll. |
| `NewSimulationLanding.jsx` | The empty state when no project is selected. |
| `icons.jsx` | Inline SVG icon set. |

### Library

| File | Role |
|---|---|
| `lib/paraview.js` | `launchParaview` / `loadIntoParaview` / `loadOrLaunchParaview` — right-click fall-through logic. Returns discriminated objects (`{kind: 'launched' \| 'loaded' \| 'conflict' \| 'no_instance'}`); only throws on 5xx / network errors. |
| `lib/slugify.js` | JS counterpart of `db.slugify` — must produce identical output. |

### USER ACTION prefix scheme

Per-phase wire prefixes the frontend prepends to messages that originate from
specific UI gestures (so the agent knows what the user just clicked):

| Phase | Question | Feedback |
|---|---|---|
| `simulation_spec` | `[USER ACTION: ...follow-up question...]\n\n` + content | `[USER ACTION: ...rejected...]\n\n` + content |
| `case_builder` | plain | `[Feedback on case]: ` + content |
| `mesh` | plain | `[Feedback on mesh]: ` + content |

Strip is regex-based on display so the user bubble doesn't show the prefix.
Backend uses the `[Feedback on case]:` / `[Feedback on mesh]:` literals to
clear `approval_pending` + `approval_kind` on feedback turns (phase-scoped).

---

## 19. Phase deep-dives

### 19.1 `simulation_spec`

- **Prompt**: [prompts/simulation_spec.txt](../prompts/simulation_spec.txt). Three
  expertise tiers (beginner/intermediate/expert) drive how aggressively the
  agent gathers info vs. assumes.
- **Output**: a markdown specification with two sections (CASE
  SPECIFICATION + CASE GOAL) plus an Assumptions & Reasoning footer.
- **Tool-side effect**: calling `present_specification` doesn't return useful
  data to the agent — the markdown comes via the `ToolUseBlock` input as the
  message streams by.
- **Geometry**: spec deliberately doesn't pin domain dimensions. The mesh
  phase owns that conversation.

### 19.2 `case_builder`

- **Prompt**: [prompts/case_builder_with_explore_agent.txt](../prompts/case_builder_with_explore_agent.txt).
  Embeds the approved spec verbatim. Hard constraint: do **not** write mesh
  dictionaries.
- **Working directory**: `cwd=Case/`. Relative paths
  (`system/controlDict`, `0/U`, `constant/turbulenceProperties`) land where
  you'd expect; absolute paths under `{openfoam_source_dir}` are required for
  source-tree lookups.
- **Validation**: the prompt asks the agent to `foamDictionary <path>` after
  writing each dict; non-zero exit means revisit.
- **Reference material**: the `openfoam2412_repository_explore` sub-agent for
  open-ended queries (≥3 direct queries to find); direct `Grep`/`Glob`/`Read`
  against absolute paths for targeted lookups.
- **Approval**: `request_approval` (no args). Generic; frontend opens
  `AcceptPanel` with case_builder copy.

### 19.3 `mesh`

- **Prompt**: [prompts/mesh_agent.txt](../prompts/mesh_agent.txt). Embeds
  the approved spec, `{openfoam_source_dir}`, and `{geometry_dir}`. Defines
  the sub-step approval workflow, ParaView open/reload procedure, and
  `paraview_operator` delegation guidance.
- **Working directory**: `cwd=project_dir` (NOT `Case/`). Relative paths
  cross `Specification/`, `Case/`, and `Geometry/` naturally.
- **Outputs**: `Case/system/{blockMeshDict, snappyHexMeshDict, …}`,
  `Case/constant/polyMesh/` (after running the mesher), Reports/screenshots.
- **ParaView access**: read verbs are auto-approved; `paraview_exec` is gated.
  The `paraview_operator` sub-agent handles multi-step scene setup; its
  write verbs are NOT pre-approved (each write floats up to the user — this
  was a deliberate choice; the easy fix if it becomes too clicky is to add
  `*PARAVIEW_WRITE_TOOLS` to mesh's `allowed_tools`).
- **Approvals**: `request_subtask_approval` (per sub-step, auto-resumes
  agent on yes) and `request_phase_advance` (terminal). The two tools have
  near-identical UX — only their descriptions tell the model when to use which.
- **Known issues**: see commit `0d1b948 add the meshing state, has some known
  bugs and will need cleanup`. The mesh-quality bar is "working mesh + clean
  `checkMesh -allGeometry -allTopology`"; the production roundtrip test asserts
  wiring only, not mesh quality.

### 19.4 `improver`

- **Prompt**: [prompts/improver_agent_draft.txt](../prompts/improver_agent_draft.txt)
  (the live template — the `_draft` suffix is historical naming, not a stub).
  Embeds the approved spec, `{project_dir}`, and `{openfoam_source_dir}`.
- **Working directory**: `cwd=project_dir`.
- **Loop**: run experiments to drive the case to convergence — each experiment
  is gated by `request_experiment_approval` before compute is spent; a mid-run
  mesh change is gated by `request_mesh_approval` before the solver re-runs.
  `max_turns=20000` makes the phase effectively unbounded.
- **ParaView**: read verbs auto-approved; **write verbs and `paraview_exec`
  exposed on the parent but gated** (no `paraview_operator` here).
- **Sub-agent**: `cfd_general_purpose` only, built per-turn.
- **Terminal**: `request_phase_advance` → `/approve-improver-phase-advance` →
  handoff (`handoffs/improver_agent.md`) → `post_process` (no kickoff yet).
- **Status**: shipped and working; behaviour still being polished.

---

## 20. post_process phase: starting position

`post_process` is the only remaining stub. What it inherits for free and what's
missing.

### Free

- **Eager subfolder**: `projects/{folder}/Reports/` already materialised at
  project creation — where post_process writes its report + plots.
- **Phase pill**: `PHASE_DISPLAY["post_process"] = "Post"` already exists in
  [routes.py](../src/api/routes.py). Frontend has a matching entry.
- **Phase transition into it**: `POST /approve-improver-phase-advance` already
  runs the improver handoff turn and creates a `post_process` session with
  `projects.phase = "post_process"`. The downstream-kickoff slot (a future
  `_POST_PROCESS_KICKOFF` next to `_IMPROVER_KICKOFF` in
  [routes.py](../src/api/routes.py)) is the next thing to wire.
- **Handoff document**: the improver writes `handoffs/improver_agent.md` during
  its post-approval turn for the post_process agent to read first.
- **File-write tracker, permission gate, sub-agent infra, approval-tool
  pattern, compaction surfacing**: all reusable as-is.

### Stubbed and needs filling

- `PHASE_CONFIGS["post_process"]` is a placeholder (sonnet-4-5, basic tools, no
  thinking, max_turns=30). All values need revisit.
- **`prompts/post_process.txt` is referenced by the config but does not exist
  on disk** — instantiating the phase as-is would fail at prompt load.
- No `src/phases/post_process.py`.
- No entry in `PHASE_HANDLERS` ([routes.py:44](../src/api/routes.py#L44)).
- No post_process kickoff turn after `/approve-improver-phase-advance`
  (`downstream_agent_starting` is hard-`false` there today).
- No AcceptPanel copy / approval-tool for post_process in `ChatColumn.jsx`.

### Open design questions

1. **Terminal gesture**. post_process is the last phase — does it end with an
   approval, or just produce `Reports/report.md` and stop?
2. **Plot generation**. Matplotlib in a Bash call vs. ParaView screenshots vs.
   `foamMonitor`-style residual plots — which tooling does the agent reach for?
3. **Report scope**. What goes in `report.md` — convergence history, field
   visualisations, validation against the spec's CASE GOAL?

---

## 21. Invariants (do not break)

Load-bearing decisions; deviating from them breaks things in non-obvious ways.

1. **Subscription auth only.** [src/api/app.py](../src/api/app.py) strips
   `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` from `os.environ` at
   import and again in lifespan. Never re-introduce a `.env` file, never load
   `python-dotenv`, never pass these to `ClaudeAgentOptions.env`.
2. **The SDK owns conversation state.** Don't replay `messages` /
   `message_segments` rows back to the LLM. Resume by `sdk_session_id`.
3. **`permission_mode="default"`** — not `"bypassPermissions"`. The allowlist
   is load-bearing.
4. **Bash + `paraview_exec` + `WebFetch` never pre-approved.** Tests in
   `tests/basic/test_permissions_config.py` and
   `tests/basic/test_mesh_phase_config.py` enforce this.
5. **`setting_sources=[]`.** No leaking the dev's local Claude Code config.
6. **`StreamEvent` and `AssistantMessage` are non-overlapping by design.** Use
   stream events for live token delta + segment accumulation; use the
   assembled message for tool-input mining and approval-tool detection.
   Don't dedupe.
7. **Custom MCP tools resolve to `mcp__<server>__<name>`.** Two servers
   currently: `cfd` (orchestration tools) and `paraview` (bridge verbs).
   Translation is done by `translate_tool_names()` in
   [src/tools/__init__.py](../src/tools/__init__.py#L60).
8. **Sub-agent tools MUST be MCP-prefixed.** `build_subagents()` routes
   them through `translate_tool_names()`. Without this the SDK silently
   drops MCP tool names and the sub-agent runs with zero tools.
   (`tests/basic/test_paraview_operator_config.py::test_subagent_tools_are_mcp_prefixed`
   pins this.)
9. **MCP servers seeded with parent ∪ sub-agent tool union.** `build_tooling`
   takes `extra_mcp_tools` so the operator's write verbs are available even
   though the mesh parent doesn't expose them in its own schema. Phase
   handlers pass `_SUBAGENT_TOOL_UNION` from `build_subagents`'s second
   return value.
10. **Project folders use `slugify(name)`.** The Python and JS slugify
    implementations must agree ([src/db.py:31](../src/db.py#L31) and
    `frontend/src/lib/slugify.js`).
11. **Frontend SSE event names are part of the API contract.** Renaming an
    event without updating `useAgentStream.js` breaks the UI silently.
12. **Eager subfolders.** `Specification/`, `Case/`, `Mesh/`, `Reports/`,
    `Geometry/`, `handoffs/` are materialised at project creation. Don't
    switch to lazy.
13. **`approval_kind` is the durable approval discriminator.** The frontend's
    `pendingKind`, the AcceptPanel copy, and the approve handler all pivot
    on it. New approval-style tools extend `_APPROVAL_KINDS` in
    [routes.py:71](../src/api/routes.py#L71) and the reducer cases — not the
    URL structure.
14. **Filesystem is the source of truth for project files.** No DB-backed
    `project_files` table. "Is-new" is per-tab UI state only.
15. **Per-phase `max_turns`.** Don't re-hardcode a global limit in
    `agent/core.py`.
16. **OpenFOAM dict tokenizer is class-based, not keyword-based.**
17. **Auth callbacks share `can_use_tool` with sub-agents.** The callback
    receives `agent_id` so the modal can prefix per sub-agent.
18. **Sub-agent display names live in two places** (backend
    `SUBAGENT_REGISTRY` and frontend `SUBAGENT_DISPLAY_NAMES` map). Keep them
    in sync.
19. **OpenFOAM v2412 only.** No syntax/keywords from other versions.
20. **`checkMesh` always with `-allGeometry -allTopology`.**
21. **`bridge.py` never imported from backend code.** It imports `vtkmodules`
    and runs ParaView side-effects at module top. Reach for the path via
    `Path(__file__).parent / "bridge.py"`.
22. **ParaView teardown via `os.killpg`, not `popen.kill()`.** The `paraview`
    binary is a shell wrapper; without group-kill `paraview-real` survives.
    Lifecycle spawns with `start_new_session=True` so the group is intact.
23. **Singleton ParaView.** One instance, one port (`PV_BRIDGE_PORT`, default
    8765). `launch()` rejects a second call with `ParaviewAlreadyRunningError`.
24. **Bridge resolves relative paths against `PV_PROJECT_ROOT`.** Not against
    `__file__`. New bridge verbs must follow the `BASE_DIR`-anchored pattern
    in `load_dataset` / `save_screenshot`.
25. **`export_snapshot` is intentionally NOT exposed to the agent.** A
    defensive test ([test_paraview_tools_layout.py](../tests/basic/test_paraview_tools_layout.py))
    trips if anyone re-adds it.
26. **`paraview_operator.tools` is computed, not literal.** Adding a verb to
    `read_paraview_state.py` or `change_paraview_state.py` propagates
    automatically.
27. **Geometry upload size is hard-capped at `MAX_GEOMETRY_SIZE_BYTES`.**
    Don't refactor `POST /geometry` to `await file.read()` (full buffer)
    without keeping the streamed-write + partial cleanup behaviour.
28. **`turn_complete.stop_reason="interrupted"` is suppressed-error state.**
    The terminal `ResultMessage` arrives with `is_error=True` for user
    interrupts; the consumer must check `active_runs.was_interrupted` before
    emitting an `error` event.

---

## 22. Things deliberately NOT done

- **No tracing / observability.** SDK is opaque from outside the subprocess.
- **No `.env` / `python-dotenv`.** Auth is subscription-only.
- **No FastAPI concurrency limits.** Single-user dev project.
- **No post_process phase implementation.** Phase 5 is the next thing to
  build; its configured prompt file (`prompts/post_process.txt`) is also
  missing. (Improver — phase 4 — is now shipped.)
- **No tutorial RAG body.** The source-tree explorer sub-agent + direct
  Grep/Glob is the substitute.
- **No `present_case` tool.** Case is presented via the live file tree.
- **No ParaView status polling / state machine.** The toolbar button has one
  transient `loading` state; backend checks status on-demand at click time.
- **`paraview_operator` write verbs are NOT pre-approved in mesh.** Each
  ParaView mutation surfaces a permission prompt in production. Reverse via
  `allowed_tools=` if it becomes too clicky.
- **No STL → polyMesh automation.** The mesh agent owns that conversation.
- **No "delete this geometry" UI.** Removing a chip doesn't delete the file;
  a future right-click + confirm on the sidebar tree could fill this gap.

---

## 23. Tests

`tests/basic/` (18 files):
- `test_active_runs.py` — interrupt registry lifecycle.
- `test_api_app_imports.py` — env-strip + lifespan smoke.
- `test_feedback_prefix_routing.py` — phase-scoped feedback prefixes clear
  `approval_pending` / `approval_kind` only in the matching phase.
- `test_geometry_upload.py` — multipart upload, sanitise, collision, cap,
  cleanup-on-failure.
- `test_interrupt_route.py` — `/interrupt` returns False on no-active-run,
  True otherwise; calls SDK `client.interrupt()`.
- `test_case_approval_route.py` — `/approve-case` SSE: case_approved →
  phase_transitioned event sequence, safety-net auto-advance, explicit-
  commit happy path, wrong-phase / 404.
- `test_commit_phase_advance.py` — `commit_phase_advance` tool
  registration, MCP-prefix translation, `_is_commit_phase_advance`
  detector (and non-crossing with sibling approval tools), return shape,
  both phases expose the tool.
- `test_mesh_approval_routes.py` — `/approve-mesh-step` clears flags
  without touching phase; `/approve-mesh-phase-advance` SSE streams
  `mesh_phase_approved` + `phase_transitioned`, safety-net auto-advance
  flips phase to `improver`.
- `test_mesh_approval_tools.py` — tool registration, MCP-prefix translation,
  event detectors for the two mesh approval tools.
- `test_mesh_phase_config.py` — mesh phase config completeness, tool-list
  invariants, subagent materialisation with MCP-prefixed tool names.
- `test_paraview_bridge_source.py` — structural pins on bridge verbs
  (`BASE_DIR` anchoring, etc.).
- `test_paraview_lifecycle.py` — `start_new_session=True`, orphan recovery,
  force-kill semantics.
- `test_paraview_operator_config.py` — operator registry entry shape and
  MCP-prefix invariant.
- `test_paraview_tools_layout.py` — read/write partitioning; `export_snapshot`
  not exposed.
- `test_paraview_tools_registry.py` — `_CUSTOM_TOOLS` map shape.
- `test_permissions_config.py` — no phase pre-approves Bash.
- `test_permissions_deny_feedback.py` — deny-with-feedback path passes the
  message through.
- `test_project_files_listing.py` — `/files` walks blessed + ad-hoc folders;
  hidden files filtered.

`tests/production/` (7 roundtrips, opt-in):
- `test_permissions_roundtrip.py` — permission gate end-to-end.
- `test_geometry_roundtrip.py` — multipart upload + file-tree refresh.
- `test_paraview_bridge_roundtrip.py` — ParaView launch + bridge verbs against
  the live binary. Gated on `shutil.which("paraview")`.
- `test_paraview_operator_roundtrip.py` — operator sub-agent applies a slice
  + colour-by-U against the sample case. Opt-in via
  `RUN_LIVE_SUBAGENT_TESTS=1`.
- `test_mesh_phase_roundtrip.py` — mesh agent writes a real `blockMeshDict`
  given a unit-cube cavity stub + skeletal `Case/`. Opt-in.
- `test_compaction_divider_roundtrip.py` — a `role="compaction"` row round-trips
  through `get_full_chat_history()` as a `{type:"compaction"}` divider in
  chronological position; malformed JSON degrades to a bare divider.
- `test_question_answer_roundtrip.py` — the `AskUserQuestion` Future handshake:
  resolving with answers returns `allow` + `updated_input`; timeout path carries
  a freeform `response`; multiSelect/"Other" pass through; unknown/already-
  resolved ids are race-safe.

Shared sample case: `tests/openFoam_test_case/difficult_w_fields.foam` (with
populated 0/ fields).

---

## 24. Source-of-truth pointers

- **Core agent loop** — [src/agent/core.py:314](../src/agent/core.py#L314)
- **Phase registry** — [src/config.py:232](../src/config.py#L232)
- **Sub-agent registry** — [src/config.py:86](../src/config.py#L86)
- **Phase handlers** — [src/phases/](../src/phases/) (`simulation_spec`, `case_builder`, `mesh`, `improver`)
- **Tool registry / MCP server** — [src/tools/__init__.py](../src/tools/__init__.py)
- **HTTP endpoints + SSE event loop** — [src/api/routes.py](../src/api/routes.py)
- **DB schema + slugify** — [src/db.py](../src/db.py)
- **Frontend reducer** — [frontend/src/hooks/useAgentStream.js](../frontend/src/hooks/useAgentStream.js)
- **Permission registry** — [src/agent/permissions.py](../src/agent/permissions.py)
- **Active-run / interrupt registry** — [src/agent/active_runs.py](../src/agent/active_runs.py)
- **File-write hook** — [src/agent/hooks.py](../src/agent/hooks.py)
- **ParaView lifecycle** — [src/paraview/lifecycle.py](../src/paraview/lifecycle.py)
- **ParaView bridge (loaded INSIDE ParaView)** — [src/paraview/bridge.py](../src/paraview/bridge.py)
- **Project conventions for AI agents** — [CLAUDE.md](../CLAUDE.md)
- **Original architecture intent (stale)** — [architecture.md](architecture.md)
- **Claude Agent SDK docs** — https://code.claude.com/docs/en/agent-sdk/

---

## 25. TL;DR for an LLM joining mid-stream

You are looking at a 5-phase agentic CFD pipeline. **Phases 1–4 are shipped
(mesh has known bugs; improver behaviour is still being polished); phase 5
(post_process) is the next thing to build — and its prompt file is missing.**
Each phase = a config entry + a prompt + a 30–40-line handler that yields events
from a shared `run_turn()`. The Claude Agent SDK owns conversation state; we
resume across turns by `sdk_session_id`. Tool permissions for sensitive
tools (Bash, `paraview_exec`, ParaView writes, `WebFetch`) gate through a
`can_use_tool` callback wired to a frontend Allow / Deny / Deny-with-feedback
panel; the built-in `AskUserQuestion` rides the same machinery into a
`QuestionPanel`. The user can interrupt a turn mid-flight via `/interrupt`.
Context compaction is surfaced to the UI (transient spinner + persisted
divider). File writes inside the project root automatically surface as toasts +
sidebar tree updates via a `PostToolUse` hook (Bash diffs by mtime; Write/Edit
reads the path from input). Approval-to-advance is one of a family of generic
MCP tools (`request_approval` / `request_subtask_approval` /
`request_experiment_approval` / `request_mesh_approval` /
`request_phase_advance`, then `commit_phase_advance` on the handoff turn)
discriminated by `projects.approval_kind`, each paired with an HTTP endpoint and
reducer case. ParaView visualisation is wired through a singleton bridge
subprocess and a `paraview` MCP server (38 verbs); the `paraview_operator`
sub-agent handles multi-step mutations in the mesh phase.

The code wins disagreements with [architecture.md](architecture.md) and other
older docs. 
