# `web_fetch` — Implementation Plan (project-fitted)

Companion to `scientific_web_fetch_spec_v3.md` (the *what*). This is the *how to
build it in **this** repo* — it supersedes the generic implementation plan, which
was written without knowledge of the codebase and explicitly punted on "project
layout, module paths, and framework wiring." Everything below is grounded in how
AgenticCFD actually wires tools, phases, the cache, and the file-write tracker.

Read the spec for pipeline semantics (fetch → normalize → handoff, the three HTML
passes, the PDF TOC ladder, the schemas). This document only covers what changes
because we are inside AgenticCFD.

---

## 0. The five project-fit facts that drive every decision

These are the things the generic plan could not have known. They are not optional
background — each one changes the design.

1. **An in-process SDK `@tool` handler receives only `args` — never the cwd or the
   project dir.** Verified against the installed `claude_agent_sdk`
   (`tool()` → `SdkMcpTool(handler=...)`; the handler signature is `async def
   fn(args: dict) -> dict`). In-process MCP servers run **in the FastAPI backend
   process**, whose `os.getcwd()` is wherever `uvicorn`/`main.py` was launched
   (the repo root) — **not** the agent's `cwd`. So the tool *cannot* discover the
   project folder by itself. The cache dir must be **injected out-of-band**
   (§3). This is the single biggest gap in the original plan, which assumed the
   tool writes "inside the agent's working dir."

2. **`Read` requires absolute paths.** Confirmed against the official tools
   reference ("Claude is instructed to always pass absolute paths"). Relative
   paths are not resolved for Read. Combined with fact #1 (the tool's own process
   cwd is unrelated to the agent's cwd) this means: **every path we hand back —
   `content_path`, every `FigureRef.image_path`, and every inline figure `src` in
   `content.md` — must be absolute.** This answers the open question directly:
   absolute, not relative-to-project_dir. The PDF page constraints in the spec are
   also confirmed: > 10 pages requires a `pages` range, max 20 pages per Read call.

3. **Tools are wired through `build_tooling()` per turn, and that function runs
   inside the phase handler, which *does* have `project_dir`.** See
   `src/phases/simulation_spec.py` → `build_tooling(...)` then `run_turn(...,
   project_dir=...)`. `create_sdk_mcp_server` is already rebuilt every turn. That
   is our injection seam (§3) — we thread `project_dir` into `build_tooling` and
   bind the cache dir into a freshly-built tool object.

4. **The file-write tracker walks the project tree on every Bash call.**
   `src/agent/hooks.py::build_file_write_tracker` registers a **PostToolUse** hook.
   For Write/Edit it reads the path from tool input (so files we write via plain
   Python `open()` never trigger it). **But for Bash it diffs a full
   `rglob("*")` of `project_dir`** and emits a `file_written` UI event for every
   new/modified file. `_scan_project` skips hidden *files* but **`rglob` still
   descends into hidden directories**, so a cache at `project_dir/.webcache/` would
   make `.webcache/source.pdf` fire phantom `file_written` events (subfolder
   `.webcache`) the next time the agent runs Bash in a phase that has Bash
   (case_builder/mesh/improver/post_process). `simulation_spec` has no Bash, so it is
   unaffected — but if we want this tool reusable across phases we must handle it
   (§4).

5. **The project layout is fixed and conventional.** `project_dir =
   PROJECTS_DIR / folder_name`, absolute (`PROJECT_ROOT = Path(__file__).parent.parent`).
   Per-project subfolders are `Specification/ Case/ Mesh/ Geometry/ Reports/
   handoffs/`, plus a hidden `.paraview_snapshots/` for transient artifacts —
   precedent for a hidden `.webcache/`. `projects/` is gitignored, so cache files
   are never committed. The `/files` UI endpoint already prunes dot-dirs at the top
   level (`entry.name.startswith(".")`), so `.webcache/` won't show in the file tree.

---

## 1. Where the code lives

A cohesive tool family in its own package + its own MCP server, mirroring the
ParaView precedent (`src/tools/paraview/` → `mcp__paraview__*`). One tool, but
enough internal machinery (fetch, pdf, html, cache, schemas) to deserve a package.

```
src/tools/web_fetch/
  __init__.py        exports WEB_FETCH_MCP_SERVER_NAME, WEB_FETCH_TOOL,
                     make_web_fetch(cache_root: Path) -> SdkMcpTool
  schemas.py         pydantic v2 models (spec §5): WebFetchInput (input),
                     Link, FigureRef, TableRef, TocEntry, DocMetadata, FetchResult
  fetcher.py         robots + SSRF + streaming + byte-ceiling + magic sniff +
                     binary short-circuit + manual redirect → bytes/type or status
  dispatch.py        magic-bytes → headers → extension  (can fold into fetcher.py)
  pdf.py             stage source.pdf + pypdf structural pass + TOC ladder
  html.py            one lxml parse → 3 passes (links / images / content) + assemble
  text.py            decode → content.txt → line count
  cache.py           content-addressed per-project store (§4)
  tool.py            the @tool handler factory: runs the pipeline, serializes
                     FetchResult into the SDK content envelope (§5)
```

Server name `web_fetch`, tool name `web_fetch` → the model sees
`mcp__web_fetch__web_fetch`. The doubled word is cosmetic (an id the user rarely
sees); a dedicated server is the default because it scopes the per-turn binding
logic (§3) cleanly. If the doubling grates, two trivial alternatives: rename the
*server* to `fetch` (→ `mcp__fetch__web_fetch`), or drop the dedicated server and
register the single tool object in the existing `cfd` server (→
`mcp__cfd__web_fetch`) — the latter means the per-turn binding lives as a small
special-case in the `cfd` registration path instead.

The tool name registered with `@tool(...)` is `web_fetch`; the input
model is `WebFetchInput` (named distinctly from the tool to avoid confusion with
the now-removed built-in `WebFetch`).

---

## 2. The tool return shape (SDK envelope, not a bare FetchResult)

SDK tools must return `{"content": [...], "is_error"?: bool}` (see every tool in
`src/tools/`). The `FetchResult` crosses the boundary as JSON text:

```python
async def _handler(args: dict) -> dict:
    result: FetchResult = await run_pipeline(args, cache_root)   # never raises
    return {
        "content": [{"type": "text", "text": result.model_dump_json(exclude_none=True)}],
        "is_error": result.status not in ("ok", "redirected"),
    }
```

- `is_error` is advisory — `redirected`/`blocked_by_robots`/`oversize`/… are
  *successful determinations*, but marking genuine failures (`fetch_error`,
  `parse_error`) as `is_error=True` matches how `paraview_exec` flags failures.
  Treat `redirected` as non-error (it's an actionable instruction to the agent).
- `usage` stays the fixed string from spec §5.6 — it's the access contract that
  tells the agent to Read `content_path`.
- For small docs, `content_inline` carries the markdown so the agent skips a Read
  round-trip; it is still *also* on disk.
- **The handler never raises.** Every failure path returns a `FetchResult` with a
  `status`. Wrap the whole pipeline in a `try/except` that converts any unexpected
  exception into `status="fetch_error"`/`"parse_error"`.

Input schema for `@tool`: a JSON-schema dict (like `paraview_exec`), `url` required
string + `force_raw` optional boolean. Do the real validation inside the handler
with the `WebFetchInput` pydantic model (so `AnyUrl` parsing/SSRF normalization
happens in one place).

---

## 3. Injecting the cache dir — the factory + `build_tooling` seam

The crux (fact #1 + #3). The handler can't find the project; we bind the cache root
into the tool object at build time, per turn.

**3a. Factory in `src/tools/web_fetch/__init__.py`:**

```python
WEB_FETCH_MCP_SERVER_NAME = "web_fetch"
WEB_FETCH_TOOL = "web_fetch"

def make_web_fetch(cache_root: Path) -> SdkMcpTool:
    @tool("web_fetch", _DESCRIPTION, _INPUT_SCHEMA)
    async def web_fetch(args: dict) -> dict:
        # cache_root is captured here — this is how the tool learns the project dir
        ...
    return web_fetch
```

**3b. `src/tools/__init__.py` — two small changes:**

`_CUSTOM_TOOLS` stays for static, import-time singletons. `web_fetch` is
the one tool whose object is per-turn, so it is **not** in `_CUSTOM_TOOLS`. Add a
name→server map so `translate_tool_names` can still prefix it, and a dynamic branch
in `build_tooling`:

```python
# name → server, for tools whose OBJECT is built per-turn (dynamic), so they
# can't live in _CUSTOM_TOOLS but still need mcp__server__name translation.
_DYNAMIC_TOOL_SERVERS = {WEB_FETCH_TOOL: WEB_FETCH_MCP_SERVER_NAME}

def translate_tool_names(names):
    out = []
    for n in names:
        if n in _CUSTOM_TOOLS:
            out.append(f"mcp__{_CUSTOM_TOOLS[n][0]}__{n}")
        elif n in _DYNAMIC_TOOL_SERVERS:
            out.append(f"mcp__{_DYNAMIC_TOOL_SERVERS[n]}__{n}")
        else:
            out.append(n)
    return out

def build_tooling(tools, allowed_tools, extra_mcp_tools=None, project_dir=None):
    visible = translate_tool_names(tools)
    allowed = translate_tool_names(allowed_tools)
    union = list(tools) + list(extra_mcp_tools or [])
    by_server, seen = {}, set()
    for n in union:
        if n in seen:
            continue
        seen.add(n)
        if n in _CUSTOM_TOOLS:
            server, obj = _CUSTOM_TOOLS[n]
            by_server.setdefault(server, []).append(obj)
        elif n == WEB_FETCH_TOOL and project_dir is not None:
            obj = make_web_fetch(project_dir / ".webcache")
            by_server.setdefault(WEB_FETCH_MCP_SERVER_NAME, []).append(obj)
    mcp_servers = {s: create_sdk_mcp_server(name=s, tools=o) for s, o in by_server.items()}
    return visible, allowed, mcp_servers
```

The `extra_mcp_tools` union already feeds the same loop, so a **sub-agent** that
lists `web_fetch` (e.g. `cfd_general_purpose`) gets the bound tool
registered too — no extra code.

**3c. Phase handlers pass `project_dir`.** One-line change per phase that uses the
tool. e.g. `src/phases/simulation_spec.py`:

```python
tools, allowed_tools, mcp_servers = build_tooling(
    _phase_cfg["tools"], _phase_cfg["allowed_tools"], project_dir=project_dir,
)
```

(`project_dir` is already a parameter of `run_simulation_spec_turn`.)

> **Why a closure and not a `ContextVar`?** A `ContextVar` set in `run_turn` would
> also reach the handler *if* it propagates into the SDK's internal tool-dispatch
> task — but that depends on unverified SDK context-propagation semantics and would
> be fragile across SDK upgrades. The closure is deterministic: the cache dir is
> baked into the handler at build time, called by reference. Simplicity + no magic.

---

## 4. The cache (per-project, absolute paths)

**Decision: per-project, on disk at `project_dir/.webcache/<url_hash>/`.** This
honors the request to keep the cache "in the project folder," matches the
`.paraview_snapshots` precedent, is auto-cleaned when a project is deleted, and is
gitignored via `projects/`. Layout per entry:

```
<project_dir>/.webcache/<url_hash>/
    source.pdf | content.md | content.txt
    figures/*.png
    meta.json            # the full FetchResult
```

- **Key:** hash of the normalized URL (lower-case host, strip fragment, keep query).
- **Absolute paths everywhere** (fact #2). `cache_root = project_dir / ".webcache"`
  is absolute because `project_dir` is. So `content_path`, `FigureRef.image_path`,
  and the rewritten inline `![](...)` `src` in `content.md` are all absolute and
  Read-able regardless of the agent's cwd.
- **TTL 24 h**, LRU/size cap (PDFs up to 50 MB). On call: if entry age < TTL, return
  stored `meta.json` paths with no network. The `web-fetch-test` project already
  exists for exercising this.

**Required infra step (fact #4):** so cache writes don't emit phantom
`file_written` events after Bash calls in Bash-enabled phases, **prune hidden
directories in `_scan_project`** (`src/agent/hooks.py`). The function's own
docstring already claims it uses the "same filter as the /files endpoint," and the
`/files` endpoint prunes whole dot-dirs at `iterdir`; the `rglob` walk currently
leaks dot-dir *contents*. Make them agree:

```python
for f in proj_root.rglob("*"):
    if f.is_file() and not any(p.startswith(".") for p in f.relative_to(proj_root).parts):
        ...   # only non-hidden files in non-hidden dirs
```

This is a 1-line correctness fix aligned with the hook's documented contract (it
also stops any latent `.paraview_snapshots` leakage), not a workaround. Flag it in
the PR so it's a conscious, reviewed change to shared infra.

> **Zero-infra-touch alternative** (if you'd rather not touch `hooks.py`): place the
> cache at `PROJECT_ROOT/data/web_fetch_cache/<project_id>/<url_hash>/` — outside
> `project_dir`, so the tree-walk never sees it. Still per-project (segmented by id),
> still gitignored (`data/`), still absolute paths. The cost is it's not literally
> *in* the project folder and isn't auto-removed when the project folder is deleted.
> Recommend the in-project `.webcache/` + the prune; fall back to this only if the
> hook change is unwanted. (To use it, the tool needs `project_id`, not
> `project_dir` — thread that through `build_tooling` instead.)

---

## 5. Dependencies (uv) and the license trap

All extraction libs are currently **missing**; `httpx` is present but only as a
**dev** dependency. This tool runs in production (the simulation_spec phase), so its
deps are runtime deps under `[project].dependencies`.

```bash
uv add httpx           # promotes it from [dependency-groups].dev to runtime
uv add "trafilatura>=1.8" pypdf protego filetype markdownify lxml
uv add pdfplumber      # optional: font-size TOC fallback (step 5b below)
```

- **License trap — verify before adding:** `trafilatura` was **GPLv3** before
  v1.8.0 and Apache-2.0 from 1.8.0 on. The spec's "≥1.8" pin is deliberate; confirm
  the resolved version is ≥1.8 and Apache-2.0 (`uv pip show trafilatura`). The
  project's "permissive only / no copyleft" rule (spec §2.5) makes this a gate, not
  a nicety. `lxml` (BSD), `pypdf` (BSD-3), `protego` (BSD-3), `filetype` (MIT),
  `markdownify` (MIT), `pdfplumber` (MIT, bundles `pdfminer.six` MIT) are clean.
- **`tiktoken`: skip it.** It is unused anywhere in the repo today (grep: zero
  references; no token-counting exists in the project at all), and `est_tokens` is
  an explicitly **non-gating** size hint — the agent reads via Read, which paginates
  regardless of the estimate. Decisive point: `tiktoken` ships *OpenAI's* BPE
  encodings, so any count it returns only approximates Claude's tokenizer — it's an
  approximation either way. A `len(text)//4` heuristic gives the same planning value
  with no added dependency and no first-use vocab download (simplicity-first). Add
  it later only if a real need appears.
- `pydantic` v2 is already present (via FastAPI). `numpy` etc. are unrelated.

No model weights, no system binaries (docling/torch/easyocr/pypdfium2 are all out
per spec §0). **The tool makes zero LLM calls**, so it never touches the SDK's
`ANTHROPIC_API_KEY`-stripping (CLAUDE.md) — no new auth surface.

---

## 6. Phase wiring

Primary home: **`simulation_spec`** (it does the literature lookup; its prompt already
points at web search and the NASA TMR — exactly this tool's target corpus). The new
tool **replaces** the built-in `WebFetch` outright. In
`src/config.py::PHASE_CONFIGS["simulation_spec"]`:

```python
"tools":         ["present_specification", "WebSearch", "web_fetch", "AskUserQuestion"],
"allowed_tools": ["present_specification", "WebSearch"],   # web_fetch NOT here → gated
```

- **Keep `WebSearch`** — it finds the URLs this tool then fetches (spec: "used after
  the official web-search tool"). It stays auto-approved.
- **Drop `WebFetch` entirely.** The built-in `WebFetch` does fetch + small-model
  markdown extraction but **does not run JS** either, so it offers nothing our tool
  doesn't — there's no JS-rendering fallback to preserve. For a genuinely JS-only
  page, the realistic recourse in `simulation_spec` is `WebSearch` to a better source
  (it has no Bash to curl with). Don't carry two fetchers.
- **Gate it exactly like `WebFetch` was** — present in `tools`, **absent from
  `allowed_tools`**, so every call routes through the `can_use_tool` callback /
  frontend permission panel. This puts `web_fetch` in the same gated set
  the project already maintains (Bash, `paraview_exec`, ParaView writes, WebFetch):
  the user vets each fetch. Do **not** auto-approve it.
- **Later phases:** `case_builder`, `mesh`, `improver`, `post_process` currently
  carry `WebFetch`; replace it with `web_fetch` (same gated posture) when
  wanted. Those phases have Bash, so they depend on the §4 `_scan_project` prune.
  `cfd_general_purpose` (sub-agent) is the natural place if you want delegated
  fetching — add the name to its `tools` in `SUBAGENT_REGISTRY`; the
  `extra_mcp_tools` path (§3b) registers the bound tool automatically.

**Prompt (`prompts/simulation_spec.txt`):** add one short, principle-style line (the
project's prompt convention is purpose+constraint, not templates): name
`web_fetch` as the preferred way to pull a found source in for close
reading, note it stages the document and hands back a local file to Read plus a
typed link/TOC map, and that data-file links are surfaced but not downloaded. Keep
it brief — don't enumerate the schema.

---

## 7. Build order (value-first, project-adapted)

Each step ends with a concrete verification (CLAUDE.md: goal-driven, don't
extrapolate success).

1. **Deps + license gate** (§5). → verify: `uv run python -c "import trafilatura,
   pypdf, protego, filetype, markdownify, lxml"` and trafilatura ≥1.8 Apache.
2. **`schemas.py`** — all pydantic models. → verify: a `tests/basic/` test builds a
   `FetchResult` and round-trips `model_dump_json` / `model_validate_json`.
3. **`cache.py` + the factory + `build_tooling` seam** (§3–4). Wire it before the
   pipeline so every path is exercised through the real injection. → verify
   (`tests/production/`): `build_tooling(["web_fetch"], [...],
   project_dir=tmp)` returns a `web_fetch` server, and the visible name is
   `mcp__web_fetch__web_fetch`.
4. **Fetch core + safety** (`fetcher.py`, `dispatch.py`) — robots, SSRF, streaming,
   byte ceiling, magic sniff, binary short-circuit, redirect handling. → verify
   (basic, mocked httpx): oversize → `oversize` before body; cross-host redirect →
   `redirected` + `redirect_url`; non-PDF binary → `binary_skipped`; SSRF host
   rejected.
5. **Text path** — trivial; proves end-to-end assembly + cache + tool dispatch with
   no extraction risk. → verify (production): fetch a `.txt`, get `content.txt`
   (absolute), `line_count`, cache hit on 2nd call (no network).
   - **5b.** **PDF stager** (`pdf.py`): stage `source.pdf`, `page_count`, embedded
     URI links, embedded metadata, TOC ladder **outline → numbered-heading regex**
     first; **font-size clustering (pdfplumber) is optional polish**, ship later.
     → verify (production): a real paper PDF yields `page_count` + a non-empty
     `toc`; a no-outline numbered paper yields a regex `toc`; un-derivable → empty
     `toc`, not an error.
6. **HTML extractor** (`html.py`), internal order per spec §4.5:
   a. **Pass 1 links + classify**, **Pass 2 images + download** (the platform-
      independent guarantees). b. **Pass 3 trafilatura + thin fallback + repeated-
      block dedup**. c. **Assemble** `content.md`, rewrite figure `src`→absolute
      local path (== `FigureRef.image_path`), build line-anchored `toc`.
   → verify (production): **TMR leaf page — every `.dat/.inp/.nml` link present and
   typed `data`, none dropped** (the headline acceptance criterion); figures
   downloaded and inline `src` absolute == `figures` index; a Doxygen/OpenFOAM page
   keeps `<pre>`/`.fragment` code verbatim; a CFD-Online thread keeps post bodies,
   drops global chrome.
7. **Result + `meta.json` assembly** + the SDK envelope (§2). → verify: handler
   returns the `{"content":[...]}` shape and never raises on any §6/spec status.
8. **Phase wiring + prompt** (§6). → verify: a `tests/production/` round-trip drives
   the tool through `build_tooling` against the `web-fetch-test` project.
9. **`_scan_project` prune** (§4) + confirm no phantom `file_written` after a Bash
   call in a Bash-enabled phase.
10. **Tuning** against fixtures (§8): font-size thresholds, thin-extraction trigger,
    repeated-block recurrence threshold, image filters.

---

## 8. Tests — `tests/basic/` vs `tests/production/` (CLAUDE.md split)

`tests/basic/` (fast, no network, mock/syntax/unit):
- schema round-trip; link classification (extension-checked-before-host;
  `mailto:/tel:/javascript:/#` dropped; chrome tagged not dropped); cache-key
  normalization; numbered-heading regex; redirect/oversize/binary status logic with
  `httpx` mocked (`httpx` is already available as a dev dep for this).

`tests/production/` (real, exercise it like production; gate live network behind an
env flag mirroring the existing `RUN_LIVE_SUBAGENT_TESTS`, e.g.
`RUN_LIVE_WEBFETCH_TESTS=1`):
- TMR index + leaf (link-harvest guarantee), real paper PDF (page_count + TOC +
  Read-by-`pages` navigability), HTML→md + figure download with absolute inline
  `src`, **cache round-trip** (2nd call no network, identical absolute paths),
  **tool-dispatch round-trip** through `build_tooling` (server registers, name maps,
  bound handler returns a valid `FetchResult` into a tmp `.webcache`).
- Fixtures from spec §7 / the generic plan §6: paper PDF with/without outline, book
  PDF, Doxygen page, vBulletin thread, TMR index, TMR leaf, chrome-heavy cross-host
  redirect stub, image-equation page, oversize guard, non-PDF binary.

Run: `uv run pytest tests/basic` and `RUN_LIVE_WEBFETCH_TESTS=1 uv run pytest
tests/production`.

---

## 9. "Done" (acceptance, project-specific additions)

The spec/plan acceptance criteria still hold (no data link ever lost; figures
Read-able by absolute path; correct structured statuses; forum content survives;
PDFs stage + carry page_count + TOC-when-derivable; 24 h cache serves without
network; no path raises; no model calls). Add the integration criteria:

- **Absolute paths only** — `content_path`, `FigureRef.image_path`, and inline
  `content.md` figure `src` are all absolute and Read-able from the agent
  regardless of the phase's cwd.
- **Cache is per-project under `project_dir/.webcache/`** and never appears in the
  `/files` UI listing nor as a phantom `file_written` event after a Bash call.
- **Dispatch round-trip works** — the tool is reachable as
  `mcp__web_fetch__web_fetch` after `build_tooling(...,
  project_dir=...)`, bound to that project's cache.
- **License gate passed** — trafilatura ≥1.8 Apache-2.0; no copyleft anywhere.
- **httpx is a runtime dependency**, not dev-only.

---

## 10. Out of scope (unchanged from the generic plan, restated for this repo)

No JS/headless rendering, OCR, docling/layout-ML, rasterization. No model/Haiku call
anywhere in the tool. No site-specific forum adapters. No `intent` parameter, no
summarization, no tier/budget machinery. Tool input is only `url`, `force_raw`. Do
**not** re-introduce an `ANTHROPIC_API_KEY`/`.env` path — irrelevant here since the
tool is pure-deterministic, but worth stating because it's a hard project rule.

---

## 11. As-built notes (what implementation revealed)

Built under `src/tools/web_fetch/` (schemas, fetcher, classify, pdf, html, text,
cache, tool, `__init__`). Wired into `simulation_spec` (gated). Deltas from the plan
above, all discovered during live validation:

- **Code preservation needed a sentinel pass, not just Doxygen→`<pre>`.**
  trafilatura **always collapses `<pre>` newlines and never fences** (verified) —
  the code fences I first saw came only from the thin-fallback markdownify path. So
  pages with prose *and* code (OpenFOAM docs, forum pastes) would lose code. Fix:
  `_extract_code_blocks` pulls every `<pre>` + Doxygen `.fragment` out to one-line
  sentinels before extraction; `_restore_code_blocks` puts them back fenced +
  verbatim after — works on both the trafilatura and markdownify paths. (Watch out:
  `lxml`'s `element.remove()` drops the element's *tail*, which is often the code —
  blank the line-number gutter in place instead.)
- **`FetchResult.error`** field added — carries the reason for
  `fetch_error`/`parse_error` so the agent can react. `is_error` in the SDK envelope
  is set only for those two (not for `redirected`/`oversize`/`blocked_by_robots`,
  which are successful determinations).
- **CFD-Online is behind a Cloudflare JS challenge** → 403 for *every* non-JS client
  (our UA, a browser UA, and the built-in WebFetch alike). Inherent, not a bug; the
  tool returns `fetch_error` with an actionable hint (use web_search/alternate). This
  is exactly the "JS-rendered pages out of scope" deferral. UA kept custom (a browser
  UA gives no access benefit; openfoam.com etc. serve the custom UA fine). Forum
  *extraction logic* is covered by a fixture test instead of a live thread.
- **The old NASA TMR (`turbmodels.larc.nasa.gov`) was decommissioned (~02/2026)** and
  cross-host-redirects to nasa.gov; the tool correctly returns `redirected`. The live
  resource is `https://tmbwg.github.io/turbmodels/` (already in the prompt). Data-link
  guarantee verified on `flatplate_sa.html` (15 `.dat`/`.inp`/`.zip` typed `data`).
- **Numbered-heading TOC hardened** (small section-number bound, letter-ratio, drop
  repeated running headers) so scanned/outline-less PDFs yield an *empty* TOC rather
  than junk. pypdf warning logger quieted.
- **User-Agent must avoid robots bot-name substrings.** robots.txt matches the UA
  by **substring**, so `…web_fetch` matched Wikipedia's `User-agent: Fetch /
  Disallow: /` and wrongly blocked *every* Wikipedia article. UA changed to
  `AgenticCFD/0.1 (+…; CFD literature reader)` — no `fetch`/`bot`/`crawl`/`spider`/
  `search` substring (note "research" contains "search"). Broad fix, not just
  Wikipedia.
- **Heading permalink anchors stripped.** Doc generators (Antora/Sphinx/MkDocs)
  append `[🔗](#overview)` to headings; removed from headings + TOC so section
  names are clean.
- **TOC noise filter.** Headings that are a bare link (forum post-author rows) or
  that repeat >3× (per-post meta like "Well-Known Member") are dropped from the TOC
  (kept in content). Doc/article/wiki TOCs are unaffected.
- **Equation images don't eat the figure budget.** Old physics pages (the TMR
  model pages) render *every* equation as a small PNG — `spalart.html` has 255
  `<img>`, ~253 of them LaTeX glyphs (`\rho` at 8×11 px). With the LaTeX in each
  `alt`, the budget (cap 15) was spent entirely on equation glyphs, missing the
  real sketches. Fix: `_is_math_alt` skips images whose alt is LaTeX (markup chars
  `\ { } _ ^`) — the equation stays inline **as text**, and the slots go to real
  figures. Verified: `spalart.html` → just the 2 sketches; `flatplate_sa.html` →
  all 15 result plots; the Azore blog's equation images (descriptive/empty alt, no
  LaTeX alternative) are still downloaded. Every downloaded file validated as a
  real, non-truncated image (PNG/JPEG/GIF) with an absolute Read-able path.
  Figure cap raised 15 → **25**.
- **`content.md` is self-contained for figures.** trafilatura drops images that
  sit in HTML table cells (TMR results pages render plots in `<td>`s), so without
  help most plots would be reachable only via the `figures` index, not the markdown
  the agent opens. `_append_figure_gallery` appends a `## Figures` section
  embedding any downloaded figure not already referenced in-position (caption +
  absolute local path). Verified: `flatplate_sa.html` → all 15 figures referenced
  (1 in-position + 14 gallery); the Azore blog (all 15 already inline) gets no
  gallery. So every downloaded figure is Read-able straight from `content.md`, and
  `figures` remains the structured index.
- **Junk-image filter widened (since the gallery makes leaks visible).** Pass 2
  DOM-sweeps *every* `<img>`, so the signal-word filter is what keeps ads/badges out.
  Found leaking on real pages: an eBay ad + a "sponsor" banner + a "decal" (XenForo
  forum), a Creative-Commons license badge (the OpenFOAM doc). Added tokens:
  ads/sponsor/spon/promo/ebay/deal(s)/premium/upgrade/affiliate, badge/ribbon/award/
  decal/emoji/smilie/reaction/license/creativecommons, avatars. Also **removed
  "thumb"** — Wikimedia serves every real article image via a `/thumb/` URL, so it
  was dropping *all* Wikipedia figures (0 → 1, the real photo, after the fix). Did
  NOT add "profile" (collides with "velocity profile" plots). Verified the real
  content survives (forum mesh screenshots, the snappyHexMesh overview diagram, the
  Wikipedia lead photo) while the ads/badges drop. It stays heuristic and
  over-keeping by design — a novel ad with no recognizable token can still slip
  through, but the agent's vision (Read) is the final filter and a stray image is
  cheap to ignore, whereas losing a real plot is not.

- **Cross-checked vs raw HTML** (link counts, code-block counts, text-extraction
  ratio) on a spread of real pages. Verified working:

  | Source | Result |
  |---|---|
  | `doc.openfoam.com/2312/…/snappyhexmesh` | ✅ content + 3 code fences verbatim + clean section TOC |
  | TMR (index / leaf / grids / SA results) | ✅ 15 `.dat`/`.inp` typed `data`; Fortran fenced; figures Read-able |
  | Wikipedia (Turbulence modeling) | ✅ full article, clean TOC, citations typed (after UA fix) |
  | Azore CFD blog | ✅ `article`, section TOC, equation images downloaded |
  | preCICE **Discourse** forum | ✅ `forum`, post bodies + OpenFOAM log fenced + plots |
  | homebuiltairplanes **XenForo** forum | ✅ `forum`, post bodies (some header chrome; TOC cleaned) |
  | arXiv PDF / NASA report PDF | ✅ staged; outline TOC / empty-not-junk TOC |
  | **cfd-online.com (forums *and* wiki)** | ❌ entire domain behind Cloudflare JS challenge → `fetch_error` 403 (inherent; affects all non-JS fetchers) |

  Tests: `tests/basic/test_web_fetch_*.py` (offline, 32) + gated live
  `tests/production/test_web_fetch_roundtrip.py` (TMR, OpenFOAM doc, Wikipedia,
  cache, dispatch — `RUN_LIVE_WEBFETCH_TESTS=1`).
