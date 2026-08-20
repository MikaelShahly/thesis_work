---
title: snappyHexMesh workflow and meshing steps
topic: workflow
keywords: [snappyHexMesh, workflow, renumberMesh, castellation, snapping, layers, blockMesh, locationInMesh, refinement level, octree, two-stage, -overwrite, foamCleanTutorials, polyMesh]
see_also: [snappyhexmeshdict-reference.md, background-mesh-and-refinement-strategies.md, boundary-layers.md, mesh-quality-and-checkmesh.md]
source: OpenFOAM Meshing Tutorial Lectures 1; Engys "A Comprehensive Tour of snappyHexMesh"
---

# snappyHexMesh workflow and meshing steps

`snappyHexMesh` builds high-quality hex-dominant meshes around arbitrary geometry. It reads a single dictionary, `system/snappyHexMeshDict`, and operates on a hexahedral background mesh plus one or more surface geometries (STL/OBJ/Nastran). The final mesh is always written to `constant/polyMesh`.

## The pipeline at a glance

1. **Background (base) mesh** — a pure-hex mesh created with `blockMesh` (or any external mesher) that fills the entire computational region. Its cell size defines refinement level 0.
2. **Geometry** — STL/OBJ surfaces placed in `constant/triSurface`, plus optional searchable primitives (box, sphere, cylinder, plane) defined directly in the dictionary.
3. **Castellation** — the base mesh is refined (feature, surface, and volume refinement) and the cells on the wrong side of the geometry are removed, leaving a valid cartesian mesh.
4. **Snapping** — surface points are projected onto the geometry to produce a body-fitted mesh.
5. **Layer addition** — optional prismatic boundary layers are inserted on selected patches.
6. **Quality enforcement and load balance** — quality is monitored continuously; the final mesh is balanced and written.

The same workflow produces both external meshes (object inside a flow domain) and internal meshes (flow inside a pipe/vessel). The only difference is where the keep-point `locationInMesh` is placed: outside the body for external flow, inside it for internal flow.

## The seven meshing steps in detail

**Step 1 — Background hexahedral mesh.** Fill the domain with pure hexes (typically `blockMesh`). The mesh must be pure hex where refinement will occur, cell aspect ratio close to 1 near the geometry, and at least one cell edge must intersect the surface. More intersections give better results, so finer background meshes near the body help. Align the background mesh with the geometry where practical. See `background-mesh-and-refinement-strategies.md`.

**Step 2 — Cell splitting at feature edges.** Cells along extracted feature edges (`.eMesh` files) are split first, controlled by the `features` list in `castellatedMeshControls`.

**Step 3 — Cell splitting at surfaces.** Cells near specified surfaces are split, controlled by `refinementSurfaces`. Additional volume splitting can be applied inside user-defined regions.

**Step 4 — Cell removal.** The keep region is identified by `locationInMesh`. A cell is kept if roughly 50% or more of its volume lies on the keep side of the surface; the rest are removed. **Place `locationInMesh` in a pure-hex region — never in a refinement transition zone**, where non-hex cells will cause problems.

**Step 5 — Volume-region splitting.** Cells inside `refinementRegions` volumes are refined further. After this step a valid castellated (cartesian) mesh exists and is already usable for simulation.

**Step 6 — Snapping.** Points are projected onto the surface to create the body-fitted mesh, controlled by `snapControls`. Default snap values are not always sufficient; save intermediate steps at high `writePrecision` so snapping can be inspected and retried. See `snappyhexmeshdict-reference.md`.

**Step 7 — Layer addition.** Prismatic layers are added on selected patches, controlled by `addLayersControls`. This step adds *no* surface or volume refinement — it pushes existing cells away from the wall and inserts layers in the gap. This is the most failure-prone stage; see `boundary-layers.md`.

## Refinement levels and cell size

All refinement is relative to the background cell size. Each refinement level splits a hex into 8 children (a quad into 4 in 2D view). The edge size at level *n* is:

```
edge size = Δ / 2^n
```

where Δ is the level-0 (background) edge length. Level 1 halves the edge, level 2 quarters it, and so on. This 2:1 jump between levels is the single most consequential property of the mesher — it governs transition quality, boundary-layer behaviour, and curvature resolution. See `refinement-control.md`.

## Strongly recommended: split castellation/snap from layer addition

Run the mesher in two passes rather than one:

- **Pass 1 — castellation + snapping only:** `castellatedMesh true; snap true; addLayers false;`. Verify the volume and surface mesh are correct before going further.
- **Pass 2 — layers only:** a second dictionary (conventionally `system/snappyHexMeshDict_bl`) with `castellatedMesh false; snap false; addLayers true;`, which reads the mesh from pass 1 and adds only the boundary layer.

This isolates layer-addition failures from surface-meshing issues and lets you iterate rapidly on layer parameters without re-running the expensive castellation/snap steps.

```bash
# Pass 1 — castellation and snapping
blockMesh
snappyHexMesh | tee log.shm
checkMesh -latestTime | tee log.checkmesh

# Pass 2 — boundary layers only (reads the mesh left by pass 1)
snappyHexMesh -dict system/snappyHexMeshDict_bl | tee log.shmbl
checkMesh -latestTime | tee log.checkmeshbl
```

The layer-only dictionary must still contain valid `castellatedMeshControls` and `snapControls` blocks (including a `locationInMesh`), even though those phases are disabled — omitting them causes a parse error.

## Running the mesher

```bash
snappyHexMesh [-overwrite] [-dict <dict>] [-parallel] [-noFunctionObjects]
```

Required inputs: `system/snappyHexMeshDict`, geometry in `constant/triSurface`, a hex background mesh (decomposed if running in parallel), `system/decomposeParDict` for parallel runs, and the standard `system` dictionaries.

### Intermediate steps and `-overwrite`

Without `-overwrite`, `snappyHexMesh` writes the three stages into time directories `1`, `2`, `3` (castellated, snapped, layers). Transfer the final stage to `constant/polyMesh` before simulating:

```bash
cp 3/polyMesh/* constant/polyMesh
rm -rf 1 2 3
checkMesh -latestTime
```

With `-overwrite`, the final mesh is written straight to `constant/polyMesh` and no intermediate states are kept — so you cannot restart from a saved castellated or snapped state.

### Parallel

`blockMesh` does not run in parallel. Decompose first, then run the mesher and `checkMesh` in parallel, then reconstruct:

```bash
surfaceFeatureExtract
blockMesh
decomposePar
mpirun -np 4 snappyHexMesh -parallel -overwrite
mpirun -np 4 checkMesh -parallel -latestTime
reconstructPar -constant     # older versions: reconstructParMesh
```

`numberOfSubdomains` in `decomposeParDict` must match the `-np` value. Serial runs sometimes produce slightly better meshes than parallel ones, particularly for snapping and layer addition — validate parallel results against a serial reference when quality is critical.

## Keep the case directory clean

Always start meshing from a clean case:

```bash
foamCleanTutorials      # clean the whole case
foamCleanPolyMesh       # erase only the mesh
```

Do not clean if you intend to restart from a previously saved castellated/snapped state. Always run `checkMesh` before computing a solution.

## Reorder cells before solving: `renumberMesh`

After meshing and before running the solver, reorder the cell numbering to improve cache locality and reduce matrix bandwidth, which speeds up the linear solvers:

```bash
renumberMesh -overwrite
```

Run it on the final mesh (after `checkMesh` passes). It changes only the cell/face ordering, not the geometry or topology, so it is safe to apply to any valid mesh and is good practice before a production run. For mesh-region splitting (e.g. conjugate heat transfer) use `topoSet` together with `splitMeshRegions`; `transformPoints` applies geometric transforms (scale/rotate/translate) to an existing mesh.

## File-name restrictions

Geometry file names — and the names of parts/regions inside them — must not contain spaces or unusual characters, and must not begin with a number.
