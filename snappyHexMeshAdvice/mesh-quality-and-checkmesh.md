---
title: Mesh quality metrics and checkMesh
topic: quality
keywords: [mesh quality, checkMesh, non-orthogonality, maxNonOrtho, skewness, maxInternalSkewness, maxBoundarySkewness, aspect ratio, smoothness, growth rate, expansion, orthogonality, minVol, minArea, minTetQuality, minTwist, minDeterminant, minFaceWeight, minVolRatio, minTriangleTwist, minConcave, relaxed, errorReduction, nSmoothScale, foamToVTK, paraFoam Include Sets, allGeometry, allTopology, writeSets, writeSurfaces, edge ratio, Mesh Quality filter, RL criterion, integral length scale, cell type, hanging nodes, primitiveMeshCheck, negative volume]
see_also: [snappyhexmeshdict-reference.md, boundary-layers.md, snappyhexmesh-workflow.md]
source: OpenFOAM Meshing Lecture 3; Engys "Comprehensive Tour" Part 2; mixing-elbow, sphere, boat-hull practical cases
---

# Mesh quality metrics and checkMesh

In CFD the mesh is everything. Always check mesh quality before solving — a good mesh may not guarantee a good solution, but a bad mesh always produces a bad one. A single bad cell can cause divergence or wrong results. There is no closed theory of mesh quality; assessment is experience-driven, iterative, and partly visual — it is usually easier to diagnose a bad mesh than to confirm a good one.

## How quality is enforced during meshing

`snappyHexMesh` monitors quality continuously. Any mesh motion or topology change that creates a cell/face violating `meshQualityControls` is undone, reverting to the last valid state. Two parameters govern the recovery: `errorReduction` (scales back the displacement field in error regions each recovery iteration) and `nSmoothScale` (smooths the scaling field). The `relaxed` sub-dictionary loosens limits during the final layer iterations so layers can be inserted where strict limits would block them. Quality enforcement is what makes meshing slow; disabling it is possible but not recommended.

## The four primary metrics

**Orthogonality / non-orthogonality.** Angular deviation between the face area vector **S** (at face centre) and the vector **d** joining the two cell centres P and N. Perfectly orthogonal ⇒ angle 0 (metric 1.0). Mainly degrades Laplacian/diffusive and gradient terms and adds numerical diffusion. Values approaching 90° indicate near-zero-volume cells; values above 90° are worse and must be corrected.

**Skewness (non-conjunctionality).** How far the point where **d** pierces the face plane lies from the actual face centre. Affects interpolation of cell-centred quantities to the face — both convective and diffusive terms — but less severely than non-orthogonality. Adds numerical diffusion and oscillations (wiggles). Common at sharp geometric angles such as wing leading edges.

**Aspect ratio (AR).** Longest cell side / shortest side. Large AR is acceptable where gradients along the long direction are small — typical of boundary layers in RANS/URANS, and not a problem on its own (it usually just signals a fine near-wall mesh). But high AR smears gradients and adds numerical diffusion; in DES/LES it adds excessive dissipation and should be minimised.

**Smoothness (expansion / growth rate / uniformity).** The size transition between adjacent cells. Keep the change ≤ 20% (`Δy₂/Δy₁ ≤ 1.2`). Avoid abrupt jumps; prefer gradual transitions. Note the inherent 2:1 jumps from `snappyHexMesh` octree refinement violate this locally — see `refinement-control.md`.

## Practical thresholds

OpenFOAM defaults are conservative. In practice good results are obtainable up to roughly **non-orthogonality 80°** and **skewness 8**, though keep skewness below ~6 where you can (numerics correct it partly). Avoid non-orthogonality near 90° (zero-volume cells). High AR is generally fine for wall-resolving meshes.

Suggested working thresholds:
- **Non-orthogonality:** 80° max.
- **Skewness:** 8 max.
- **Aspect ratio:** depends on wall units; wall-resolving meshes naturally give high values.

A simulation *can* run with quality errors (high skewness/AR/non-orthogonality), but accuracy suffers, results may be unexpected, and the solver may eventually diverge. With lower-quality meshes, adapt the numerical schemes accordingly. When values exceed the thresholds, inspect the mesh and decide — based on the physics and the number/location of bad cells — whether to remesh or to proceed with error-tolerant schemes.

Built-in defaults live in `primitiveMeshCheck.C` (`$WM_PROJECT_DIR/src/OpenFOAM/.../primitiveMeshCheck/` in OpenFOAM 11 and earlier; `$WM_PROJECT_DIR/src/meshCheck/` in OpenFOAM 12). Default values: `nonOrthThreshold = 70°`, `skewThreshold = 4`, `aspectThreshold = 1000`, `closedThreshold = 1e-6`, `planarCosAngle = 1e-6`.

## meshQualityControls metrics in full

Each `meshQualityControls` entry maps to a geometric check. Decompositions use the cell centre and face centres; vectors below: $\vec{A}_i$ face area vector, $\vec{c}_i$ owner-to-neighbour cell-centre vector, $\vec{b}_i$ cell-centre-to-face-centre vector.

- **`maxNonOrtho`** — max non-orthogonality angle. Metric = $(\vec{A}_i\cdot\vec{c}_i)/(|\vec{A}_i||\vec{c}_i|)$ (1.0 = orthogonal). Typical 65–75°; relax to ~75 during layers.
- **`maxBoundarySkewness` / `maxInternalSkewness`** — skewness = $|\vec{d}_i|/|\vec{c}_i|$ (distance from face centre to where the cell-to-cell line crosses the face, normalised). Internal faces held tighter (default 4) than boundary (default 20) because they affect interpolation directly.
- **`maxConcave`** — max interior face angle before a face is concave (e.g. 80°). Concave faces hurt gradient and flux evaluation.
- **`minVol` / `minArea`** — min cell-pyramid volume $\tfrac13(\vec{A}_i\cdot\vec{b}_i)$ and min face area $|\vec{A}_i|$. **Negative pyramid volume = inside-out cell = solver crash.** Set a tiny positive value (e.g. `1e-13`) to catch degenerate cells while passing legitimately small ones.
- **`minTetQuality`** — quality of the cell's tet decomposition (from circumradius and tet volume). Needed positive so inside-cell tests (streamlines etc.) work, but too-high values reject valid cells. A very small or large-negative value (e.g. `1e-30` or `-1e30`) effectively disables it while still catching fully degenerate tets — recommended for best layer insertion.
- **`minTwist`** — face-twist metric $(\vec{f}_i\cdot\vec{c}_i)/(|\vec{f}_i||\vec{c}_i|)$; detects warped faces. Typical 0.02–0.05.
- **`minDeterminant`** — determinant of the tensor built from the cell's face-area vectors, normalised by 0.03703 (a perfect hex). Must be well-conditioned for `fvc::reconstruct`. Typical 0.001. **This is the metric that most often blocks fine boundary layers with relative sizes** — reduce or negate it to restore coverage (see `boundary-layers.md`).
- **`minFaceWeight`** — interpolation-weight balance $\min(d_{nei},d_{own})/(d_{own}+d_{nei})$ (0.5 = perfectly centred). Typical 0.05. **Most common blocker for absolute-size boundary layers.**
- **`minVolRatio`** — owner/neighbour volume ratio $\min(V)/\max(V)$ (1.0 = equal). Typical 0.01 (cells may differ by up to ×100). Can become the limiter for very fine boundary layers (near-wall ~10⁻⁶).
- **`minTriangleTwist`** — dot product of neighbouring sub-triangle unit normals; detects severely warped faces. `-1` disables it; least critical metric.
- **`minVolCollapseRatio`** (commented by default) — lets boundary-only cells survive if projecting their points to the surface changes volume by less than the ratio. Can cause stability issues from poorly-connected regions, hence off by default.

### Relative importance

Most critical (failure ⇒ crash or severe instability): `maxNonOrtho`, `minVol`, `minArea`, `minTetQuality`, `minTwist`, `minDeterminant`, `minFaceWeight`, `minVolRatio`. Important but survivable if mildly violated: `maxBoundarySkewness`, `maxInternalSkewness`, `maxConcave`. Least critical: `minTriangleTwist`.

## checkMesh

`checkMesh` reports element counts, topology, and geometry/quality. No dictionary needed; runs in parallel with `mpirun`. Failed cells/faces are written as sets in `polyMesh/sets`.

```bash
checkMesh [-allGeometry] [-allTopology] [-writeSets] [-writeSurfaces] \
          [-latestTime] [-parallel] [-region name]
```

- **Topology** (failure ⇒ crash): boundary definition consistent, no unused points, upper-triangular ordering, valid/unique face vertices, single contiguous region. **Number of regions** is reported here — 1 for a normal mesh, 2+ after baffle-splitting for sliding meshes.
- **Patch topology** (serial): each patch's connectivity — closed/non-closed singly connected, or multiply connected through a shared point/edge. Multiply connected ⇒ usually a crash.
- **Geometry/quality**: bounding box, openness, max aspect ratio, face-area and cell-volume ranges, non-orthogonality (max/avg), face-pyramid status, skewness. Critical geometric checks (boundary openness, non-orthogonality, min volume, face pyramids) failing ⇒ crash; skewness/AR/min-area less critical.

```
Mesh non-orthogonality Max: 66.36 average: 9.80
***Max skewness = 7.40, 109 highly skew faces detected
<<Writing 109 skew faces to set skewFaces
Failed 1 mesh checks.
```

Topology and patch-topology errors **must** be fixed before solving. Quality errors (skewness, AR, min-area, non-orthogonality) can be tolerated but degrade accuracy. `checkMesh` does **not** repair anything — fix the geometry and remesh. Unused points are harmless and removable with `topoSet` + `subsetMesh`.

### Verbose diagnostics

`-allGeometry -allTopology` adds pyramid cells, wrongly-oriented faces, concave cells, warped/short edges, near-coincident points. `-writeSets -writeSurfaces` saves the offending cells/faces for ParaView. Extended-metric errors are less critical than the basic ones but worth reviewing for very fine meshes.

```bash
checkMesh -allGeometry -allTopology -writeSets -writeSurfaces
```

This correlates problems with specific features. For example, cells with 18–30 faces (vs ~12 ideal) typically occur at pinch points where a 2:1 transition collapses, and the saved sets locate them precisely.

Always run `surfaceCheck` on the input STL/OBJ too — illegal triangles, small faces, and inconsistent normals there propagate into the mesh (see `geometry-preparation.md`).

### Visualising the faulty sets

- **paraFoam wrapper:** enable **Include Sets** and pick the set (only works with the `paraFoam` wrapper).
- **ParaView directly / large meshes:** convert to VTK first:

```bash
foamToVTK -faceSet  skewFaces
foamToVTK -cellSet  highAspectRatioCells
foamToVTK -pointSet unusedPoints
```

General form `foamToVTK -<faceSet|cellSet|pointSet|surfaceFields> <name>`; output goes to a `VTK/` directory.

## Monitor aspect ratio across the three stages

Check max AR after each stage to localise where problems start:

- **After castellation:** ≈ 1.0 (slightly higher in transitions; ~1.16 typical and fine).
- **After snapping:** rises as cells distort to fit the surface. ≤ ~3 is safe for layers; 3–6/8 may work with tricks; > 8–10 means the surface mesh needs more refinement *before* attempting layers.
- **After layers:** rises further with thin prisms — here the pass/fail of quality checks matters more than the absolute AR.

If AR is already high after snapping, add surface refinement. If AR is fine after snapping but layers fail, the problem is the layer parameters or metric conflicts, not the surface mesh.

## ParaView Mesh Quality filter (edge ratio)

The **Mesh Quality** filter's **Edge Ratio** (longest/shortest edge) corresponds most closely to the AR `snappyHexMesh` uses during layer addition. Set the colour max to ~100–200; cells near/over 100 are where layers collapse. Add a **Threshold** filter (> 100) for a volumetric view of the problem regions. Polyhedral cells have no defined edge ratio and show as 0 (blue) — a ParaView limitation, not an error.

The three numbers — spreadsheet prediction, `checkMesh` AR, ParaView edge ratio — generally differ (each uses different definitions/corrections; e.g. `checkMesh` 37 vs ParaView 200 on the same cells). Use them for different jobs: spreadsheet for planning, `checkMesh` for automated pass/fail, ParaView for spatial location. **Always inspect visually** — `checkMesh` can report acceptable values that mask poor geometry, and vice versa.

## Choosing cell types

Hexahedral, prismatic, and quadrilateral cells stretch well to resolve boundary layers without quality loss; tets/tris have inherently larger truncation error. Truncation error drops when faces align with the flow and dominant gradients — for boundary layers there is no ambiguity: use hex or prism.

- **Hex:** most accurate per cell, especially aligned with the flow; loses its edge in complex flows without a dominant direction.
- **Polyhedral:** good gradients (many faces), but skewness/small-face-area issues grow with face count and the solution can go oscillatory; growth rate and refinement are hard to control.
- **Tet:** fewest faces ⇒ less accurate gradients, but adapts to any geometry with controllable growth and conforming volumetric refinement.

Modern numerics narrow the historical tet-vs-hex accuracy gap — with good schemes all types give comparable results, and hybrid meshes are fine. Use hex when high force accuracy matters (drag prediction) or for turbomachinery. Hanging nodes (polyhedral faces joining hexes of different size) simplify generation but add numerical diffusion at the rapid size transition — important to control in LES.

Structured and unstructured methods both work with good practice; unstructured is generally easier to generate; structured can be slightly better in some situations.

## Physics-based adequacy: the R_L criterion

Beyond pure grid-refinement studies (slow, and misleading when models behave non-monotonically under refinement — drag can even rise on finer grids), assess adequacy against turbulent scales. Compute the integral length scale from a two-equation model:

```
l₀ = k^1.5 / ε        or        l₀ = k^0.5 / (C_μ · ω),   C_μ = 0.09
```

Then `R_L = l₀ / Δ`, with Δ ≈ cube root of cell volume (valid for AR below ~1.2). Targets: `R_L > 5–10`; ≥ 10 for accurate LES, 5 the lower limit for DES/LES, 4–5 sufficient for RANS/URANS/VLES. Refine where `R_L` falls below the threshold. This combines turbulence-model information with grid information in a single number.

## General quality guidance

Make the mesh dense enough to capture all relevant flow features; use larger cells where the solution changes slowly. More cells generally improves accuracy at higher cost, but a finer mesh is not automatically better — especially with turbulence models. Cluster cells only where needed (non-uniform meshes, local refinement, solution adaptation). Without wall functions, near-wall meshes must resolve the boundary layer, which can put 50%+ of all cells in the inflation zone — and when layers are fine, the surface mesh must be refined to match, or the prism aspect ratio becomes excessive. Keep orthogonality, skewness, and AR low and size changes smooth, and resolve geometric features (curvature, gaps, surface AR). Low-aspect-ratio surface meshes tend to satisfy all of these at once.
