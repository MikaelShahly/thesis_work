---
title: INDEX — snappyHexMesh meshing advice router
topic: index
keywords: [index, router, symptom, troubleshooting, navigation, snappyHexMesh, meshing, table of contents, where to look]
source: consolidated snappyHexMesh / OpenFOAM meshing knowledge base
---

# snappyHexMesh meshing advice — INDEX

Canonical advice for meshing with `snappyHexMesh` (OpenFOAM v2412 / openfoam.com syntax). Start here, then open the specific topic file. Every file has a `keywords:` line in its front matter, so `grep -ril "<term>" .` finds the right document fast.

> Syntax note for the whole KB: this is **openfoam.com (v2412)** syntax. Refinement uses the tuple form `levels ((distance level))`; the bare `level N;` form is openfoam.org (Foundation) syntax and fails in v2412. STL/OBJ geometry goes in `constant/triSurface`.

---

## Symptom → file (start here when meshing is failing)

| Symptom / error | Go to |
|---|---|
| Boundary layers won't grow / 0% or partial coverage | `boundary-layers.md` |
| Layers collapse at a sharp / trailing / leading edge | `boundary-layers-at-sharp-edges.md`, `boundary-layers.md` |
| Layers fail and log names a metric (determinant, face weight, vol ratio) | `boundary-layers.md` (troubleshooting via quality metrics) |
| High non-orthogonality | `mesh-quality-and-checkmesh.md` |
| High skewness | `mesh-quality-and-checkmesh.md` |
| High aspect ratio | `mesh-quality-and-checkmesh.md`, `boundary-layers.md` |
| `checkMesh` reports negative / zero cell volume | `mesh-quality-and-checkmesh.md`, `boundary-layers.md` |
| Surface mesh "jumps" / interpenetrates across a narrow gap | `refinement-control.md` (gap refinement) |
| Snapping artefacts / poor body-fit at edges | `snappyhexmeshdict-reference.md` (snapControls troubleshooting) |
| Restart inconsistency: "inconsistent cellLevel / pointLevel" | `background-mesh-and-refinement-strategies.md` (delete metadata files) |
| Refinement region applied in the wrong place / inside-out | `geometry-preparation.md` (normals), `refinement-control.md` |
| Volume refinement not applied where expected | `refinement-control.md`, `snappyhexmeshdict-reference.md` |
| Mesh too big / out of memory during refinement | `background-mesh-and-refinement-strategies.md` (background refinement), `boundary-layers.md` |
| Curvature under-resolved (faceted curves) | `refinement-control.md` (1 cell / 10°) |
| Free-surface initial interface is a staircase | `free-surface-vof-meshing.md` |
| AMI weights not ≈ 1 / interpolation error at rotating interface | `sliding-meshes-ami-mrf.md` |
| `checkMesh` reports 1 region but sliding mesh needs 2 | `sliding-meshes-ami-mrf.md` (createBaffles/splitBaffles) |
| Need a 2D mesh | `2d-meshing.md` |
| Only one patch after meshing / patches missing | `patches-and-boundary-conditions.md` |
| Patch type / field type mismatch error at run time | `patches-and-boundary-conditions.md` |
| Force coefficients wrong / off by depth factor | `2d-meshing.md`, `patches-and-boundary-conditions.md` |
| Velocity oscillates though residuals look converged | `patches-and-boundary-conditions.md` (fix outlet pressure reference) |
| Backflow / divergence at the outlet | `patches-and-boundary-conditions.md` (inletOutlet) |
| Small geometry: cells truncated / precision issues | `geometry-preparation.md`, `free-surface-vof-meshing.md` |
| STL not watertight / disconnected regions | `geometry-preparation.md` |
| Feature edges not captured / missing edges | `geometry-preparation.md` (extraction), `refinement-control.md` (application) |
| Layers expected but only some surfaces got them | `refinement-control.md` (faceType), `boundary-layers-at-sharp-edges.md` |
| Expecting smooth growth rate but getting abrupt 2:1 jumps | `snappyhexmesh-limitations-and-tool-comparison.md` |

---

## Topic → file

| Topic | File |
|---|---|
| Overall pipeline, the 7 steps, running the mesher, two-stage workflow | `snappyhexmesh-workflow.md` |
| Full `snappyHexMeshDict` reference (every section + recommended values) | `snappyhexmeshdict-reference.md` |
| Background (`blockMesh`) mesh, M1–M4 strategies, background refinement | `background-mesh-and-refinement-strategies.md` |
| STL/OBJ prep, MeshMixer, normals, watertight, feature-edge extraction, fillets, write precision | `geometry-preparation.md` |
| Surface/region/edge/gap/BOI refinement, faceType, 2:1 transition, curvature | `refinement-control.md` |
| Quality metrics, thresholds, `checkMesh`, `foamToVTK`, R_L, cell types | `mesh-quality-and-checkmesh.md` |
| Boundary layers: spec, aspect-ratio wall, troubleshooting, defaults | `boundary-layers.md` |
| Layers at sharp edges: virtual surface, cyclicAMI, right-angle junctions | `boundary-layers-at-sharp-edges.md` |
| Sliding mesh / AMI / MRF, baffles, dynamicMeshDict, MRFProperties | `sliding-meshes-ami-mrf.md` |
| 2D meshing with `extrudeMesh` | `2d-meshing.md` |
| Patch creation/renaming + boundary conditions (external aero & internal) | `patches-and-boundary-conditions.md` |
| Free-surface (VOF) waterline alignment and refinement | `free-surface-vof-meshing.md` |
| Limitations, ANSYS comparison, meshing philosophy | `snappyhexmesh-limitations-and-tool-comparison.md` |

---

## Case type → where to look (and what's specific to it)

The advice below is organised by topic, not by physical case, so several docs apply to every case. This table collects, per case type, the docs that apply and the regime-specific points to watch. Universal docs — `snappyhexmesh-workflow.md`, `snappyhexmeshdict-reference.md`, `geometry-preparation.md`, `mesh-quality-and-checkmesh.md`, `boundary-layers.md` — apply to **all** cases and are not repeated each row.

| Case type | Read these (beyond the universal set) | Regime-specific points |
|---|---|---|
| **External flow over a bluff body / vehicle / building** | `patches-and-boundary-conditions.md` (external-aero BCs), `refinement-control.md` (BOI/wake), `background-mesh-and-refinement-strategies.md` | `locationInMesh` **outside** the body; far-field BCs (inletOutlet outlet, fixed outlet pressure, symmetry vs slip); ground-plane refinement; wall modelling vs resolving; wake refined with a BOI, not distance-from-surface. |
| **Internal flow (pipe, duct, vessel, manifold)** | `refinement-control.md` (uniform interior refinement), `patches-and-boundary-conditions.md` (internal BCs), `background-mesh-and-refinement-strategies.md` | `locationInMesh` **inside** the body; background box slightly larger than geometry; **refine the interior uniformly** so surface AR is uniform and layers grow; opposing-wall layers can collide in narrow passages — combined thickness must fit the gap. |
| **Free-surface / multiphase (hull, tank, channel — VOF)** | `free-surface-vof-meshing.md`, `background-mesh-and-refinement-strategies.md` (multi-block alignment) | Align a cell **face** with the waterline (multi-block + `mergePatchPairs`) or `setFields` gives a staircase; `searchablePlane` + `mode distance` band around the interface; auxiliary planes via `refinementRegions`, never `refinementSurfaces`; high `writePrecision`/binary for model scale. |
| **Rotating machinery (mixer, pump, turbine, propeller)** | `sliding-meshes-ami-mrf.md`, `geometry-preparation.md` (split the shaft at the interface) | Choose sliding mesh (transient, split into 2 regions, `cyclicAMI`) vs MRF (steady, `cellZone` only); match interface refinement on both sides; create cell/face-zones at meshing time; `createBaffles`/`splitBaffles`; check AMI weights ≈ 1. |
| **2D (airfoil, cylinder, any extruded section)** | `2d-meshing.md` | One-cell-thick background, mesh in 3D then `extrudeMesh`; lateral patches `empty`; `thickness 1` for force coefficients; implicit (not explicit) feature snapping. |
| **Aerofoil / wing / blade with a sharp trailing edge** | `boundary-layers-at-sharp-edges.md`, plus `2d-meshing.md` if 2D | Layers collide at the sharp edge — add a fillet, or use the virtual-surface (synCup) technique with `faceType boundary` and `cyclicAMI` coupling; trailing-edge collapse is usually acceptable, leading-edge collapse is not. |
| **Bodies with narrow gaps (underbody–ground, close clearances)** | `refinement-control.md` (gap refinement, BOI) | Resolve ≥2 cells across the gap (`gapLevel`/`gapLevelIncrement` on **both** bounding surfaces); a thin BOI box across the gap gives the most control; watch for surface-mesh "jumping" if only one cell spans the gap. |

> Note: a few cautions cut across cases — e.g. pin a reference outlet pressure and verify velocity visually (both internal and external), and keep refinement transitions away from the body (all cases). These are stated in each relevant doc rather than centralised here.

---

## File manifest

- **`snappyhexmesh-workflow.md`** — the meshing pipeline end to end: background mesh → castellation → snapping → layers; refinement-level formula `Δ/2^n`; the recommended two-pass (castellate/snap, then layers) workflow; `-overwrite`, parallel runs, case cleaning, file-name rules.
- **`snappyhexmeshdict-reference.md`** — complete dictionary reference: `geometry`, `castellatedMeshControls`, `snapControls` (+ recommended values and snapping-troubleshooting order), `addLayersControls`, `meshQualityControls`, debug/write flags, `mergeTolerance`, the `boundary` file.
- **`background-mesh-and-refinement-strategies.md`** — `blockMesh`; four fine-near-wall strategies (M1–M4); the background-refinement (searchableBox pre-refinement) technique with the mandatory metadata-file cleanup; cell-size arithmetic; multi-block forced face alignment; keeping transitions away from the body.
- **`geometry-preparation.md`** — STL vs OBJ; MeshMixer groups + Inspector; normals (`surfaceCheck`/`surfaceOrient`/ParaView); watertight surfaces and multi-body closed solids; splitting for rotating machinery; fillets; write precision for small geometry; feature-edge extraction (`surfaceFeatureExtract`, manual `.eMesh`, ParaView).
- **`refinement-control.md`** — the 2:1 transition and its consequences; surface/region/edge refinement; `level` vs `levels` syntax; `gapLevelIncrement` vs `gapLevel`/`gapMode`/`gapSelf`; bodies of influence; `faceType`; curvature (1 cell/10°); uniform interior refinement; the maximum rule.
- **`mesh-quality-and-checkmesh.md`** — quality theory (ortho/skew/AR/smoothness); all `meshQualityControls` metrics with formulas and importance; default vs practical thresholds; `checkMesh` (verbose flags, sets, `foamToVTK`); aspect-ratio monitoring across stages; ParaView edge-ratio inspection; cell-type choice; the R_L criterion.
- **`boundary-layers.md`** — the big one: displacement mechanism; layer specification (`finalLayerThickness`/`firstLayerThickness`, relative vs absolute, `minThickness`); the aspect-ratio wall (~100) and the three ratio limits; planning formula; troubleshooting via quality metrics (`minDeterminant`/`minFaceWeight`/`minVolRatio`, `nLayerIter 1`); `refineWallLayer`; very fine layers (y⁺<1); recommended defaults; quick reference.
- **`boundary-layers-at-sharp-edges.md`** — the virtual-surface (synCup) technique; `faceType boundary` and the `_slave` patch; `cyclicAMI` conversion via `foamDictionary`; `mergeTolerance`; right-angle-junction collisions and sequential layer addition.
- **`sliding-meshes-ami-mrf.md`** — AMI/`cyclicAMI`/`cyclicACMI`; matching interface resolution; cell/face-zone creation in snappy; `createBaffles`/`splitBaffles` + `createBafflesDict`; `dynamicMeshDict` (single and multi-body); `MRFProperties`; AMI BCs; `moveDynamicMesh -checkAMI`.
- **`2d-meshing.md`** — meshing a one-cell-thick slab and collapsing with `extrudeMesh`; `empty` patches; `thickness 1` for force coefficients; implicit feature snapping for 2D.
- **`patches-and-boundary-conditions.md`** — `autoPatch`/`surfaceToPatch`/`createPatch`; renaming/retyping via `foamDictionary`/`sed`; base vs numerical types; external-aerodynamics and internal-flow BC combinations; the `inletOutlet` and fixed-outlet-pressure cautions; wall modelling vs resolving.
- **`free-surface-vof-meshing.md`** — aligning a cell face with the waterline (multi-block + `mergePatchPairs`); `searchablePlane` + `mode distance` refinement band; auxiliary surfaces via `refinementRegions`; write precision for model-scale hulls.
- **`snappyhexmesh-limitations-and-tool-comparison.md`** — the 2:1 limitation; ANSYS Fluent comparison (growth rates, pre- vs post-inflation, identical AR ceiling, student cell limit); `fluent3DMeshToFoam` import notes; the meshing-philosophy principles.

---

## Key numbers quick reference

| Quantity | Value | Notes |
|---|---|---|
| Cell edge at refinement level *n* | `Δ / 2^n` | Δ = background edge length |
| Refinement transition ratio | 2:1 (fixed) | not user-adjustable; root cause of most issues |
| Boundary-layer collapse aspect ratio | ≈ 100 | surface edge / near-wall height |
| Near-wall to outer-layer ratio limit | ≈ 32 (2⁵) | total-thickness limit |
| Hard aspect-ratio cap (OpenFOAM) | ≈ 1000–2000 | limits thinnest near-wall cell |
| Curvature resolution target | ≥ 1 cell / 10° | of arc |
| Gap resolution target | ≥ 2 cells across a gap | use `gapLevel` for control |
| `finalLayerThickness` (relative) start | 0.5 | with `relativeSizes true` |
| `expansionRatio` start | 1.2 | |
| Default quality thresholds | nonOrtho 70°, skew 4, AR 1000 | from `primitiveMeshCheck` |
| Practical quality limits | nonOrtho ≤ 80°, skew ≤ 8 | with suitable schemes |
| `nCellsBetweenLevels` | 3 | default, generally adequate |
| `resolveFeatureAngle` start | 30 | lower to capture more curvature |
| Wall modelling y⁺ | 30–60, ~3 layers | start here |
| Wall resolving y⁺ | < 5 (ideally < 1), +5–6 layers | expensive |
| `mergeTolerance` | < `controlDict` write tolerance | template default 1e-8 |

## First moves when a mesh is failing

1. `checkMesh -latestTime` (and `-allGeometry -allTopology -writeSets`) — read which check fails and where.
2. Identify the stage: castellation, snapping, or layers (run them separately — see `snappyhexmesh-workflow.md`).
3. Monitor max aspect ratio after castellation, after snapping, after layers — this localises the problem (`mesh-quality-and-checkmesh.md`).
4. Most layer failures are aspect-ratio failures — the fix is usually a finer/more uniform surface mesh, not relaxed metrics (`boundary-layers.md`).
5. Always inspect the mesh visually in ParaView; metrics alone mislead in both directions.