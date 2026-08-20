"""End-to-end roundtrip for the mesh phase.

A stub simulation specification + minimal case skeleton handed to the
mesh phase agent. The test verifies the **loop** and **tool
dispatch**, per plan §5.6:

- `request_subtask_approval` is emitted at least once (the
  `subtask_approval_requested` SSE event surfaces from
  src/agent/core.py).
- A `blockMeshDict` lands in `Cases/baseline/system/` (the agent
  actually wrote the file via the Write tool).

The mesh need not be "good" — we are exercising the wiring, not the
quality of the agent's meshing choices. The case used here is a
trivial unit-cube cavity that any OpenFOAM 2412 mesh agent can
realise with a single-block `blockMesh`.

Skipped when any of:

- ``RUN_LIVE_SUBAGENT_TESTS`` not set — opt-in to avoid burning LLM
  budget on every CI run.
- ``claude`` CLI not on PATH — the SDK shells out to it.
- OpenFOAM source tree not present at the configured location — the
  agent's prompt and the `openfoam2412_repository_explore` sub-agent
  both expect to navigate it.

On failure the test dumps the full SDK transcript and the event
type counts so the next investigator doesn't fly blind.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from src.config import OPENFOAM_SOURCE_DIR
from src.phases.mesh import run_mesh_turn


def _claude_cli_available() -> bool:
    return shutil.which("claude") is not None


def _openfoam_source_available() -> bool:
    return Path(OPENFOAM_SOURCE_DIR).is_dir()


pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("RUN_LIVE_SUBAGENT_TESTS"),
        reason=(
            "Live mesh roundtrip is opt-in (real LLM calls cost tokens). "
            "Set RUN_LIVE_SUBAGENT_TESTS=1 to enable."
        ),
    ),
    pytest.mark.skipif(
        not _claude_cli_available(),
        reason="Claude Code CLI ('claude') not on PATH.",
    ),
    pytest.mark.skipif(
        not _openfoam_source_available(),
        reason=(
            f"OpenFOAM 2412 source tree not found at {OPENFOAM_SOURCE_DIR} — "
            "set up the install or patch src.config.OPENFOAM_SOURCE_DIR."
        ),
    ),
]


_STUB_SPEC = """\
# Simulation specification

## Overview

Incompressible laminar flow inside a unit cube cavity. The top wall
(`movingWall`) slides at U = (1, 0, 0) m/s; the remaining five walls
(`fixedWalls`) are no-slip. The fluid is a Newtonian liquid with
kinematic viscosity nu = 0.01 m^2/s.

## Geometry

Single rectangular block, 1.0 m × 1.0 m × 0.1 m. Origin at one
corner. No external geometry file — the case builder is expected to
realise the geometry through `blockMesh`.

## Mesh

[ASSUMED] Uniform Cartesian grid sufficient to resolve a low-Reynolds
flow; 20×20×1 cells is a reasonable starting point. The case is
effectively 2D (single cell in z) with an `empty` boundary condition
on the front/back patches.

## Patches

- `movingWall` — top face (z+ is top in 3D terms; in this layout the
  top is the face at y = 1.0).
- `fixedWalls` — the four side walls.
- `frontAndBack` — `empty` patch on the two z-faces.

## Solver

`icoFoam` (incompressible, transient, laminar). Time step and end
time are not your concern — the case builder set up `controlDict`.
"""


# A skeletal case the mesh agent walks into. controlDict /
# fvSchemes / fvSolution / transportProperties are the kind of files
# the case-builder would have written before approval. The 0/ fields
# (U, p) are also pre-populated so the case is structurally complete
# *except* for the mesh-related dictionaries.
_CONTROL_DICT = """\
FoamFile { version 2.0; format ascii; class dictionary; object controlDict; }
application     icoFoam;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         0.5;
deltaT          0.005;
writeControl    timeStep;
writeInterval   20;
purgeWrite      0;
writeFormat     ascii;
writePrecision  6;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;
"""

_FV_SCHEMES = """\
FoamFile { version 2.0; format ascii; class dictionary; object fvSchemes; }
ddtSchemes      { default Euler; }
gradSchemes     { default Gauss linear; }
divSchemes      { default none; div(phi,U) Gauss linear; }
laplacianSchemes{ default Gauss linear orthogonal; }
interpolationSchemes { default linear; }
snGradSchemes   { default orthogonal; }
"""

_FV_SOLUTION = """\
FoamFile { version 2.0; format ascii; class dictionary; object fvSolution; }
solvers
{
    p { solver PCG; preconditioner DIC; tolerance 1e-06; relTol 0.05; }
    pFinal { $p; relTol 0; }
    U { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-05; relTol 0; }
}
PISO { nCorrectors 2; nNonOrthogonalCorrectors 0; pRefCell 0; pRefValue 0; }
"""

_TRANSPORT_PROPERTIES = """\
FoamFile { version 2.0; format ascii; class dictionary; object transportProperties; }
nu              0.01;
"""

_U_FIELD = """\
FoamFile { version 2.0; format ascii; class volVectorField; object U; }
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform (0 0 0);
boundaryField
{
    movingWall   { type fixedValue; value uniform (1 0 0); }
    fixedWalls   { type noSlip; }
    frontAndBack { type empty; }
}
"""

_P_FIELD = """\
FoamFile { version 2.0; format ascii; class volScalarField; object p; }
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform 0;
boundaryField
{
    movingWall   { type zeroGradient; }
    fixedWalls   { type zeroGradient; }
    frontAndBack { type empty; }
}
"""


def _materialise_project(root: Path) -> None:
    """Set up the project layout the mesh phase handler expects.

    Cwd at the project root, subfolders matching the
    PROJECT_SUBFOLDERS convention, the approved spec written into
    `Specification/`, and a skeletal case (no mesh dicts yet)
    under `Cases/baseline/`.
    """
    (root / "Specification").mkdir(parents=True, exist_ok=True)
    (root / "Geometry").mkdir(parents=True, exist_ok=True)
    case = root / "Cases" / "baseline"
    (case / "system").mkdir(parents=True, exist_ok=True)
    (case / "constant").mkdir(parents=True, exist_ok=True)
    (case / "0").mkdir(parents=True, exist_ok=True)

    (root / "Specification" / "simulation_specification.md").write_text(_STUB_SPEC)

    (case / "system" / "controlDict").write_text(_CONTROL_DICT)
    (case / "system" / "fvSchemes").write_text(_FV_SCHEMES)
    (case / "system" / "fvSolution").write_text(_FV_SOLUTION)
    (case / "constant" / "transportProperties").write_text(_TRANSPORT_PROPERTIES)
    (case / "0" / "U").write_text(_U_FIELD)
    (case / "0" / "p").write_text(_P_FIELD)


@pytest.mark.asyncio
async def test_mesh_phase_produces_blockmesh_and_requests_approval(tmp_path):
    """Drive one mesh turn against a skeletal cavity case.

    Asserts the two plan §5.6 invariants:
    1. `subtask_approval_requested` fires at least once during the
       turn (the agent has reached a sub-step boundary and called
       `request_subtask_approval`).
    2. `Cases/baseline/system/blockMeshDict` exists on disk afterwards
       (the agent actually wrote the file).

    Either failure mode (no approval event, no blockMeshDict) means
    the wiring is broken — either the tool isn't being detected /
    surfaced as an event, or the agent isn't reaching the
    write-and-present step in its workflow.
    """
    project_dir = tmp_path / "mesh-roundtrip"
    project_dir.mkdir()
    _materialise_project(project_dir)

    event_types: list[str] = []
    transcript: list[str] = []

    user_message = (
        "Begin meshing. The case is in `Cases/baseline/`; the approved spec "
        "is at `Specification/simulation_specification.md`. Present your strategy "
        "and then build the mesh."
    )

    try:
        async for ev in run_mesh_turn(
            user_message=user_message,
            expertise_level="intermediate",
            resume_session_id=None,
            project_dir=project_dir,
        ):
            event_types.append(ev.type)
            # Compact transcript: type plus a few keys from the data,
            # truncated. Enough to debug a failure without bloating the
            # log on success.
            data_preview = (
                str(ev.data)[:200] if ev.data else ""
            )
            transcript.append(f"{ev.type}: {data_preview}")

        # ── Verify ────────────────────────────────────────────────
        assert "subtask_approval_requested" in event_types, (
            "request_subtask_approval never fired during the turn. "
            f"Events seen: {sorted(set(event_types))}"
        )

        blockmesh_path = project_dir / "Cases" / "baseline" / "system" / "blockMeshDict"
        assert blockmesh_path.is_file(), (
            f"blockMeshDict not written at {blockmesh_path}. "
            f"Events seen: {sorted(set(event_types))}"
        )
        # Non-trivial content — guards against an accidental empty
        # write.
        contents = blockmesh_path.read_text()
        assert "blocks" in contents.lower(), (
            "blockMeshDict written but doesn't appear to contain a "
            f"`blocks` section. First 500 chars:\n{contents[:500]}"
        )
    except Exception:
        print("\n========== EVENT TRANSCRIPT ==========")
        for line in transcript:
            print(line)
        print("\n========== EVENT TYPE COUNTS ==========")
        from collections import Counter
        for et, n in Counter(event_types).most_common():
            print(f"  {et}: {n}")
        print(
            f"\nblockMeshDict exists: "
            f"{(project_dir / 'Cases' / 'baseline' / 'system' / 'blockMeshDict').is_file()}"
        )
        raise
