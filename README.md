# AgenticCFD (Agent SDK build)

An end-to-end agentic CFD pipeline built on the [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview). The user describes a flow problem in natural language; a multi-phase agent pipeline produces, meshes, runs, and reports on a complete **OpenFOAM 2412** simulation. The shell is FastAPI + SSE on the backend and React + Vite on the frontend; the LLM layer is `claude-agent-sdk`, which subprocesses the Claude Code CLI.

NOTE: tool approvals are handled in the config. Set a tool in tools": [], but do not include it in allowed_tools to gate the tool with approval, usefull if you DO NOT WANT arbitrary bash permission for the agent. 

## What it does

```
[1. Simulation Spec]   → Specification/simulation_specification.md
        ↓ user approves the spec
[2. Case Builder]   → Case/{0,constant,system}/...        (no mesh dictionaries)
        ↓ user approves the case
[3. Mesh]           → Case/system/{blockMeshDict, snappyHexMeshDict, ...}
                      Case/constant/polyMesh/             (after running the mesher)
                      live ParaView visualisation alongside
        ↓ user approves the mesh
[4. Improver]       → iteratively run experiments + fix the case until convergence
        ↓ user approves the result
[5. Post-process]   → Reports/report.* + plots
```

The user experiences **one continuous chat**; internally each phase is a fresh agent session with its own system prompt, model, tools, and sub-agents. Conversation state is owned by the SDK (resumed per phase by `sdk_session_id`); the local `messages` table is a UI mirror only and is never replayed back to the LLM.

**All five phases are shipped** (`simulation_spec`, `case_builder`, `mesh`, `improver`, `post_process`). Mesh has some known rough edges and the improver's behaviour is still being polished.

For the full architecture — process model, SSE event vocabulary, approval patterns, invariants — see [docs/project_state.md](docs/project_state.md).

## Prerequisites

| Tool | Version (known-good) | Notes |
|---|---|---|
| **Python** | 3.10+ (3.10.12 here) | |
| **[uv](https://docs.astral.sh/uv/)** | 0.10+ | Python env + dependency management |
| **Node.js** + npm | 20.x (20.20.2 here) | Frontend **and** the Claude Code CLI the SDK shells out to |
| **Claude Code CLI** | 2.1+ | On `PATH`, authenticated against your Claude Code **subscription** (see §1) |
| **OpenFOAM** | **v2412** | At `/usr/lib/openfoam/openfoam2412`; must be **sourced** so solvers/utilities are on `PATH` (see §2) |
| **ParaView** | **5.13.x binary tarball** | Required by the mesh + improver phases; the fiddly one (see §3) |
| **Blender** *(optional)* | headless 5.x tarball | Only for agent-driven geometry creation; detected on `PATH`, not bundled (see §4) |
| **poppler-utils** *(optional)* | distro package | Provides `pdftoppm`, which the Claude Code Read tool uses to render PDF pages as images. Without it, text-layer PDFs still extract fine; only figure-based / scan-only PDFs are lost. `sudo apt-get install -y poppler-utils` |

Quick sanity check that the CLIs are reachable:

```bash
which claude && claude --version
which paraview && paraview --version
which blender && blender --version          # optional; geometry-creation escalation only
which pdftoppm                              # optional; lets the agent visually read PDF figures
```

## 1. Authenticate the Claude Code CLI

This project authenticates against your **Claude Code subscription only** — never via an Anthropic API key. The backend actively strips `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` from its process environment at startup, so the SDK subprocess cannot fall back to API-key auth even if you've exported one.

One-time setup:

```bash
claude          # the first run launches the OAuth flow in your browser
```

After that, `claude` is logged in and the SDK uses those credentials automatically.

> **Heads up**: Anthropic's terms generally restrict offering apps that authenticate against other people's claude.ai accounts. Subscription-auth is fine for *your own* local development; do not deploy this configuration as a service for others.

## 2. OpenFOAM v2412

The agent runs OpenFOAM utilities (`blockMesh`, `snappyHexMesh`, `checkMesh`, `foamDictionary`, `simpleFoam`, …) via Bash, and the `case_builder` source-explorer sub-agent reads the install tree. Both require OpenFOAM **2412** installed and its environment **sourced** in the shell that launches the backend:

```bash
source /usr/lib/openfoam/openfoam2412/etc/bashrc      # add to ~/.bashrc to make it permanent
which blockMesh && which simpleFoam                   # should resolve after sourcing
```

If your install lives elsewhere, update `OPENFOAM_SOURCE_DIR` in [src/config.py](src/config.py) (it defaults to `/usr/lib/openfoam/openfoam2412`).

## 3. ParaView

The **mesh** and **improver** phases drive a live ParaView window through an HTTP bridge. The backend launches ParaView as `paraview --script=src/paraview/bridge.py`, and the bridge runs inside ParaView's bundled Python (`import paraview.simple`, `vtkmodules`). Install the official Kitware tarball to ensure compatibility.

The known-good build for this project is **ParaView 5.13.3, the MPI / Linux / Python 3.10 x86_64 tarball**.

```bash
# 1. Download from https://www.paraview.org/download/
#    Choose: version 5.13.x · OS "Linux" · the "MPI" + "Python 3.10" x86_64 .tar.gz
#    (The page is form-gated; to pull the exact tarball straight into WSL instead:)
#    wget -O ParaView-5.13.3-MPI-Linux-Python3.10-x86_64.tar.gz \
#      "https://www.paraview.org/paraview-downloads/download.php?submit=Download&version=v5.13&type=binary&os=Linux&downloadFile=ParaView-5.13.3-MPI-Linux-Python3.10-x86_64.tar.gz"
# 2. Extract into your home directory:
tar -xzf ParaView-5.13.3-MPI-Linux-Python3.10-x86_64.tar.gz -C "$HOME"
# 3. Put its bin/ on PATH (append to ~/.bashrc to make it permanent):
echo 'export PATH="$HOME/ParaView-5.13.3-MPI-Linux-Python3.10-x86_64/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
# 4. Verify:
which paraview && paraview --version       # → paraview version 5.13.3
```

Additional notes:

- **Discovery.** The backend locates ParaView via `paraview` on `PATH`, or via an explicit `PARAVIEW_EXECUTABLE` environment variable ([src/paraview/lifecycle.py](src/paraview/lifecycle.py)). If you keep multiple versions installed, set `PARAVIEW_EXECUTABLE` to the exact binary you want. The bridge listens on port `8765` (override with `PV_BRIDGE_PORT`).
- **Display required.** The project launches the full ParaView GUI, not headless `pvpython`. On WSL2 this needs WSLg (Windows 11) or a running X server; on a headless server it needs a virtual display such as `xvfb`. Without a display, launch fails.
- **Qt/xcb libraries (fresh Ubuntu/WSL).** The tarball bundles its own Qt but relies on the system's X11/xcb client libraries. On a clean Ubuntu 22.04 / WSL these are missing, so even `paraview --version` aborts with `Could not load the Qt platform plugin "xcb" ... even though it was found`. Install them once:
  ```bash
  sudo apt-get install -y libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 \
    libxkbcommon-x11-0 libgl1-mesa-glx libqt5gui5
  ```
- **Keep `bin/` on PATH.** The `paraview` binary is a wrapper script that execs `paraview-real`, and the backend group-kills the process tree on teardown. Add the distribution's `bin/` directory to `PATH` rather than symlinking individual binaries.
- **Python build.** The bridge always runs inside ParaView's own bundled interpreter, so the system Python version does not need to match the build's `Python3.10`; the two simply happen to align here.
- **When it's needed.** ParaView is only exercised from the mesh phase onward. The backend boots without it; you just cannot launch the visualisation until it is installed.

## 4. Geometry creation (CAD stack + optional Blender)

When a problem has no uploaded geometry, the `simulation_spec` and `mesh` agents can **author the surface geometry** (STL/STEP) that feeds meshing. Two layers back this:

- **A Python CAD stack — installed automatically by `uv sync`** (it's in [pyproject.toml](pyproject.toml)): `cadquery`, `sdf` (fogleman SDF modeling, pulled from git), `manifold3d`, `pymeshfix`, `trimesh`, `scipy`, `pyvista`, `pymeshlab`, and `gmsh`. The agent reaches for whichever tool models the shape most easily; nothing extra to install. (`vtk` is pinned to **9.3.1** to keep this stack working — see [pyproject.toml](pyproject.toml)/`uv.lock`.)
  - **System libraries (fresh Ubuntu/WSL).** `pymeshlab` and `gmsh` are compiled extensions that link against X11/OpenGL system libraries at import time; these are **not** captured by `uv`. On a clean install `import pymeshlab` aborts with an `ImportError` until they're present. Install once:
    ```bash
    sudo apt-get install -y libgl1 libglu1-mesa libxrender1   # pymeshlab
    sudo apt-get install -y libxft2                            # additionally for gmsh
    ```
    `pymeshlab` importing cleanly is the real test; `gmsh` is optional, so its `libxft2` only matters if you use it.
- **An optional headless Blender binary.** The agent **detects Blender on `PATH`** and escalates to free-authored `bpy` scripts (run via `blender --background --python …`) only when a shape exceeds the Python tools. Blender is **not bundled and not wired into the code** — it is purely a binary the agent invokes through Bash if present.

To enable the Blender escalation path, install a headless Blender tarball and put it on `PATH`:

```bash
# Download a Blender tarball from https://www.blender.org/download/
tar -xf blender-5.1.2-linux-x64.tar.xz -C "$HOME"
echo 'export PATH="$HOME/blender-5.1.2-linux-x64:$PATH"' >> ~/.bashrc
source ~/.bashrc
which blender && blender --version
```

Without Blender the pipeline still runs; the agent simply stays within the Python CAD stack. (Uploaded geometry — see the geometry upload endpoint — bypasses this entirely.)

## 5. Backend setup

From the project root, in a shell where OpenFOAM has been sourced (§2):

```bash
uv sync                  # creates .venv and installs locked dependencies (uses uv.lock)
uv run python main.py
```

The API comes up on [http://127.0.0.1:8000](http://127.0.0.1:8000) with auto-reload scoped to `src/`. Routes live under `/api`.

On first start the backend will:
- Strip `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` from the process env.
- Create `data/agenticcfd.db` (SQLite, gitignored).
- Create `projects/` on demand. Each project eagerly materialises `Specification/`, `Geometry/`, `Cases/`, and `handoffs/` ([routes.py](src/api/routes.py) `PROJECT_SUBFOLDERS`); the agent creates one named OpenFOAM case per study under `Cases/` (e.g. `Cases/baseline/`).

## 6. Frontend setup

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Vite serves the UI at [http://localhost:5173](http://localhost:5173). The backend CORS config ([src/api/app.py](src/api/app.py)) whitelists that origin.

Open the UI, create a project, and chat with the simulation-spec agent. Approving the spec continues the same chat into `case_builder`, then `mesh`, then `improver`, then `post_process` — each transition gated by an explicit approval in the UI.

## Running tests

```bash
uv run pytest tests/basic                       # fast syntax/config/unit tests
RUN_LIVE_SUBAGENT_TESTS=1 uv run pytest tests/production   # opt-in; some need ParaView on PATH
```

`tests/basic/` are mock/config tests; `tests/production/` exercise real round-trips (DB persistence, tool dispatch, SDK resumption, the live ParaView bridge) and are opt-in via `RUN_LIVE_SUBAGENT_TESTS=1` and/or a reachable `paraview` (production tests also skip when `claude` or the OpenFOAM source tree is absent).

## Project layout

```
src/
  api/
    app.py            FastAPI app, lifespan, env-strip
    routes.py         22 endpoints + SSE turn buffering + phase dispatch
  agent/
    core.py           SDK ↔ StreamEvent translation; segment persistence
    session_manager.py  Persistent SessionWorker per (project, phase); run_via_worker(); ClaudeAgentOptions builder
    session_registry.py Worker lifecycle / close-check / interrupt
    permissions.py    can_use_tool registry (allow / deny / deny-feedback)
    active_runs.py    Live client registry for /interrupt
    hooks.py          PostToolUse → file_written tracker (Write/Edit/Bash)
    subagents.py      Registry → AgentDefinition builder (+ MCP tool union)
  phases/
    simulation_spec.py   Phase handler (Opus 4.8)
    case_builder.py   Phase handler (Sonnet 4.6, sub-agent, cwd=project root)
    mesh.py           Phase handler (Opus 4.8 [1m], sub-agents, ParaView, cwd=project root)
    improver.py       Phase handler (Opus 4.8 [1m], cfd_general_purpose sub-agent, cwd=project root)
    post_process.py   Phase handler (Sonnet 4.6, report skills, cwd=project root)
  tools/
    __init__.py       build_tooling() — built-in + MCP tools
    present_spec.py, request_*.py   orchestration @tools (approval / phase-advance gating)
    paraview/         ParaView MCP server: read (11) / write (30) / exec (1) verbs
    web_fetch/        Custom WebFetch (SSRF-guarded fetch → PDF/HTML/text staging, 50 MB cap)
    paper_search/     Academic search (OpenAlex / Semantic Scholar / arXiv / NASA NTRS)
    quick_viz/        Headless pvbatch one-shot render (YAML config → PNG)
  paraview/
    lifecycle.py      launch() / is_running() / force-kill; orphan recovery; crash-log capture
    bridge.py         Loaded INSIDE ParaView (paraview --script=…); never imported by backend
  config.py           Paths, PHASE_CONFIGS, SUBAGENT_REGISTRY, geometry extensions
  db.py               SQLite schema (8 tables) + accessors
prompts/              Phase + sub-agent prompt templates (live + historical drafts)
frontend/             React + Vite client
data/                 SQLite DB (gitignored, runtime)
projects/             Per-project work folders (gitignored, runtime)
tests/
  basic/              27 syntax/config/unit tests
  production/         16 round-trip integration tests (opt-in)
docs/                 architecture.md (original, stale) + project_state.md (current snapshot)
main.py               uvicorn entrypoint
```
