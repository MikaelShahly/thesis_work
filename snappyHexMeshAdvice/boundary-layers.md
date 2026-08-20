---
title: Boundary layers — specification, the aspect-ratio wall, and troubleshooting
topic: boundary-layers
keywords: [boundary layer, layers, addLayersControls, nSurfaceLayers, finalLayerThickness, firstLayerThickness, expansionRatio, relativeSizes, minThickness, aspect ratio, layer collapse, 0% coverage, near-wall distance, y+, yplus, minDeterminant, minFaceWeight, minVolRatio, nLayerIter, refineWallLayer, geometric progression, spreadsheet, displacement, push away, coverage, wall resolving, wall modelling, additionalReporting, two-stage, snappyHexMeshDict_bl]
see_also: [snappyhexmeshdict-reference.md, background-mesh-and-refinement-strategies.md, refinement-control.md, mesh-quality-and-checkmesh.md, boundary-layers-at-sharp-edges.md, snappyhexmesh-workflow.md]
source: sphere/hemisphere, NACA0012, Wolf-logo, mixing-elbow practical cases; quick layers advice
---

# Boundary layers — specification, the aspect-ratio wall, and troubleshooting

Layer addition is the most failure-prone stage of `snappyHexMesh`. Failures are almost always geometric — the layer cells hit an aspect-ratio or ratio limit and the mesher collapses them — and the real fix is usually a finer surface mesh, not relaxed quality metrics. This document explains why layers fail and how to make them grow.

## Work in two stages

Generate castellation + snapping first, verify it, then add layers in a separate pass with `snappyHexMeshDict_bl` (`castellatedMesh false; snap false; addLayers true;`). This isolates layer failures and lets you iterate on layer parameters in seconds instead of re-running the whole mesh. The layer-only dictionary must still contain valid (if disabled) `castellatedMeshControls`/`snapControls` blocks including a `locationInMesh`, or it will not parse. See `snappyhexmesh-workflow.md`.

```bash
snappyHexMesh -dict system/snappyHexMeshDict_bl | tee log.shmbl
checkMesh -latestTime | tee log.checkmeshbl
```

## How layers are added: the displacement mechanism

Layer addition is a **post-processing step** on the finished volume mesh. It does **no** refinement. It works by **pushing the existing surface-adjacent cells away from the wall** and inserting prismatic layers in the gap, then smoothing to maintain quality. This is the key to understanding every failure mode: if the total layer thickness is too large relative to the cell next to the surface, the displaced cells collide with their neighbours or enter transition regions, violating quality metrics and collapsing.

Practical total-thickness limits relative to the adjacent cell:
- **1–2×** the adjacent cell size — generally safe.
- **3×** — starts to cause problems.
- **4–5×** — almost certainly collapses as displaced cells collide.

This is why `relativeSizes true` with `finalLayerThickness 0.5` is a safe default: it keeps the total thickness bounded relative to the local mesh automatically.

## Layer specification — choosing the right method

The two fundamental choices are which thickness to fix and whether sizes are relative or absolute.

### Prefer `finalLayerThickness` with `relativeSizes true` (strongly recommended)

`finalLayerThickness` sets the outermost layer cell as a fraction of the adjacent volume cell. With `expansionRatio`, the layers form a geometric progression growing inward from the wall, and the boundary-layer-to-volume transition is inherently smooth because the outer layer is defined relative to its neighbour.

```openfoam
relativeSizes       true;
expansionRatio      1.2;
finalLayerThickness 0.5;   // 50% of the adjacent volume cell
minThickness        0.0001;
```

This is the easiest method to control and gives the best transitions. 0.5 is a good general start; 0.7 can also work; 100% is not recommended. Lower it (e.g. 0.3) if local surface refinement shrinks the near-wall volume cells enough that the layers would exceed them. Near-wall distance and total thickness follow directly from the geometric series and can be predicted in a spreadsheet before meshing.

### `firstLayerThickness` — harder to control

Fixes the wall cell height directly (fraction of adjacent cell if relative; metres if absolute). The layers grow outward via `expansionRatio`, but the outer height is no longer constrained, so the boundary-layer-to-volume transition can be abrupt, especially with varying surface cell sizes. The same aspect-ratio limit (~100) applies.

When you need it (e.g. to hit a specific y⁺), first mesh with `finalLayerThickness`, read the resulting near-wall distance and total thickness from the log, then switch to `firstLayerThickness` matched to those values — starting from a known-good geometric state.

### `minThickness` — a common silent failure

If `minThickness` is too high (e.g. 0.1 with `relativeSizes true`), the mesher may silently grow **no** layers, reporting 0% coverage with no obvious error. For fine layers set it very small (`0.0001` or `0.001`).

### Relative vs absolute sizes

`relativeSizes true` (default, recommended): each surface cell's layer scales to its own size, adapting automatically to varying surface refinement; the outer transition is inherently smooth. Where surface cells differ a lot (different levels across a surface), the layer height varies correspondingly — visually non-uniform but robust.

`relativeSizes false` (absolute): every surface cell gets the same near-wall distance — visually uniform — but the outer transition is no longer automatically smooth; where volume cells are large relative to the fixed layer, an abrupt jump appears, a frequent cause of collapse at refinement transitions. With absolute sizes the **total** layer thickness must be of the same order as the adjacent surface cell, or the layer count needed for a reasonable thickness produces extreme aspect ratios and ratio violations.

Guidance: for **uniform** surface refinement, relative is strictly preferred (easier, better transitions, less failure-prone). Absolute can help only when surface refinement is **highly non-uniform** (e.g. level 2 over the body, level 6 at sharp edges), because the fixed wall distance avoids tiny layers in small cells and huge layers in large cells — but the outer transition must then be accepted as imperfect. To switch: run relative first, note near-wall distance and total thickness from the log, configure absolute to match.

## The aspect-ratio wall — why layers fail

The governing limit is the boundary-layer cell **aspect ratio**: surface cell edge (longest) / layer height normal to the wall (shortest). When AR exceeds **~100**, the layer-addition algorithm collapses the cells. This is the single most common cause of failure. (The AR `snappyHexMesh` computes internally differs from a naive geometric prediction because it applies smoothing/face-swapping corrections — predictions correlate well up to ~20–30 and diverge above.)

There are three hard ratios that bound how many layers you can grow:

1. **Near-wall to last-layer ratio ≤ ~32 (= 2⁵).** The ratio between the near-wall cell height and the cell just outside the boundary layer. When parameter combinations push it past ~30, layers fail.
2. **Surface-edge to total-normal-distance ratio ≤ ~100.** Largest surface edge / total boundary-layer normal distance. Past 100 the geometric progression takes it to 200 very quickly and failure is likely.
3. **Aspect ratio ≤ ~1000 (hard-coded in OpenFOAM).** Limits how thin near-wall cells can be relative to surface edge length. Going below 1000 at a thin near-wall distance needs very fine surface refinement (level 7–8), which is very expensive.

Using the geometric progression you can predict failure in advance. For example, 20 layers on one airfoil configuration is predicted to violate the near-wall ratio and does fail; 18 succeeds. **Stay well below the computed limit — at least two levels below.**

### Aspect-ratio planning formula

Given background size `dx`, surface refinement level `L`, `finalLayerThickness`, `expansionRatio`, and `nLayers`, the effective surface cell is `dx / 2^L`. The near-wall (first) cell height is:

```
h_wall = (finalLayerThickness × dx / 2^L) × (expansionRatio − 1)
         / (expansionRatio^nLayers − 1)
```

and AR ≈ `(dx / 2^L) / h_wall`. As `nLayers` rises, `h_wall` falls and AR climbs toward the collapse threshold.

Example: `dx = 0.2`, level 2 (surface cell 0.05), `expansionRatio 1.2`, `finalLayerThickness 0.5` → 5 layers comfortable (AR ≈ 5); 23 layers borderline (100% coverage but near the limit); 25 layers fails with default quality settings.

A secondary limit: when total thickness reaches ~2⁵ = 32× the near-wall height, problems begin. In practice the AR≈100 limit is usually hit first, but for very high layer counts the total-thickness limit can trigger too.

### Use the surface/region level, not the edge level

For the effective surface cell size, use the highest **surface** or **region** refinement level — **not** the edge (`features`) level. Edge refinement does not affect the layer calculation. If surface refinement is 4 and edge refinement is 6, use 4. See `refinement-control.md`.

## Finer surface meshes are the real fix

The fundamental solution to layer failure is to refine the surface mesh, not relax quality metrics. Smaller surface cells reduce AR for a given near-wall distance, allowing more layers and finer near-wall resolution without hitting the wall. Whenever layers fail, consider increasing surface refinement by one level before touching quality parameters — it addresses the root cause (excess AR) rather than masking the symptom.

Increase surface resolution by: raising `refinementSurfaces` level; adding a `refinementRegion` at a higher level around the body; or — most memory-efficiently — the **background refinement technique** (pre-refine the background near the body), which multiplies surface resolution without exploding total cell count. See `background-mesh-and-refinement-strategies.md`.

## Troubleshooting failed layers via quality metrics

When coverage is 0% or partial, the log identifies which metric collapsed the layers. Relax that metric selectively.

**`minDeterminant` — most common with `relativeSizes true`.** Default 0.001 is the usual blocker for fine layers. Reduce by an order of magnitude, or negate to disable.

```openfoam
minDeterminant  0.001;    // default — often too strict
minDeterminant  0.0001;   // first attempt
minDeterminant -1;        // disables the check (allows growth; may leave poor cells)
```

**`minFaceWeight` — most common with `relativeSizes false`.** Default 0.05; reduce to 0.02 or 0.01.

**`minVolRatio` — very fine meshes (near-wall ~10⁻⁶).** The tiny-cell-to-neighbour volume ratio exceeds the threshold; reduce or disable (negative).

**Disable multiple metrics (e.g. for trailing-edge collapse).** Removes non-orthogonality and skewness checks:

```openfoam
maxNonOrtho         180;   // 180 disables the non-ortho check
maxBoundarySkewness -1;    // negative disables
maxInternalSkewness -1;
```

**`nLayerIter 1` — disable all quality iteration (debugging).** Not zero — zero does not work. Inserts layers in a single pass with no smoothing/correction, almost always giving 100% coverage regardless of quality settings. Use it to confirm the layer geometry is fundamentally correct before selectively re-enabling metrics. The result may contain negative-volume or low-quality cells, so validate with `checkMesh`.

```openfoam
nLayerIter  1;   // last-resort debugging; do NOT set to 0
```

Also set `minTetQuality` and `minVol` to large negative values for best layer insertion (a positive `minVol`/`minTetQuality` can conflict with layer addition).

### Selective troubleshooting workflow

1. Read the log; identify the failing metric (e.g. "determinant", "face weight").
2. Reduce that metric by one order of magnitude in `meshQualityDict`; re-run.
3. If coverage improves but isn't 100%, reduce further or disable (negative).
4. If the metric is unclear, set `nLayerIter 1` to confirm layers can grow at all, then progressively re-enable checks.
5. **Always inspect the final mesh visually in ParaView** — `checkMesh` can report acceptable metrics while the geometry is poor, and vice versa.

Enable `additionalReporting yes;` in `addLayersControls` for extra layer-process diagnostics, and `grep` the log for the metric name to find the culprit.

## `refineWallLayer` — post-processing alternative

`refineWallLayer` splits the near-wall cell after meshing, with no quality enforcement:

```bash
refineWallLayer stlSurface 0.5     # splits the wall-adjacent cell in half
```

Repeat with a geometric progression to build many thin layers. A robust recipe: mesh with **one** boundary layer (which almost always succeeds), optionally make that single layer thick (`finalLayerThickness 2.0`), then apply `refineWallLayer` repeatedly to subdivide it. Brute-force — the result may have high non-orthogonality or AR, so check it.

## Per-patch parameters

Layer count and growth can differ per patch — useful where curvature differs. A tighter pipe takes a gentler growth rate:

```openfoam
layers
{
    pipe_large { nSurfaceLayers 5; expansionRatio 1.2; finalLayerThickness 0.5; minThickness 0.01; }
    pipe_small { nSurfaceLayers 5; expansionRatio 1.1; finalLayerThickness 0.5; minThickness 0.01; }
}
```

For internal flows where opposing walls are close, the layers from both walls can collide in the centre — the combined thickness must fit the available gap. Uniform interior refinement (see `refinement-control.md`) gives uniform surface AR and dramatically improves coverage versus a non-uniform interior.

## Very fine layers (y⁺ < 1) and wall-resolving meshes

Pushing the near-wall distance toward 10⁻⁴–10⁻⁶ m:

- **10⁻⁴ m** — straightforward with standard parameters and moderate surface refinement (level 2–3).
- **10⁻⁵ m** — achievable with care; `minDeterminant` is usually first to fail (set `-1`).
- **10⁻⁶ m** — very challenging; needs surface level 4+, AR exceeds 1000 (so disable `minDeterminant`), `expansionRatio` may need 1.3, `finalLayerThickness` reduced to 0.2 or lower.

The limiter is always AR = surface edge / near-wall height. Reducing near-wall height without reducing surface edge produces extreme AR; the only way to lower AR at a fixed near-wall height is finer surface refinement, which is expensive.

For **wall-modelling** (y⁺ ≈ 30–60), 3–5 layers suffice and are a good place to start for setup and validation. For **wall-resolving** (y⁺ < 5), add ~5–6 more layers and often 2–3 more surface refinement levels — a large jump in cell count and memory. Start wall-modelling; pursue wall-resolving only when the physics demands it (transition, detailed separation). See also `external-aerodynamics` notes in `patches-and-boundary-conditions.md`.

## Coverage verification and accepting defects

A reported coverage above ~90% is generally acceptable. **The log coverage figure can be misleading — always verify visually in ParaView** (use `writeFlags layerFields` to write a per-cell coverage field; see `snappyhexmeshdict-reference.md`). 91% in the log can look much worse if the collapse sits at a critical feature.

Learn to accept small defects in genuinely hard regions. Collapse localised at a **trailing edge** is usually unimportant for the solution; collapse at a **leading edge** (where transition is critical) needs attention. For sharp-feature collapse, the most effective fixes are adding fillets in CAD, local refinement at the trouble spot (`refinementRegions` `mode distance`), or raising overall surface refinement (expensive). Chasing perfect coverage everywhere produces very expensive meshes for little benefit. See `boundary-layers-at-sharp-edges.md`.

## Recommended default parameters

A robust starting point for a wide range of cases (not universal — complex geometry may need adjustment):

**`addLayersControls`:**

```openfoam
relativeSizes             true;
expansionRatio            1.2;
finalLayerThickness       0.5;
minThickness              0.0001;
nGrow                     0;
featureAngle              130;       // up to 330 to resist premature collapse at features
maxFaceThicknessRatio     0.5;
maxThicknessToMedialRatio 0.3;       // 0.3–0.6 depending on geometry
minMedialAxisAngle        90;
nBufferCellsNoExtrude     0;
nLayerIter                50;
nRelaxedIter              20;
nRelaxIter                5;
```

**`meshQualityDict`:**

```openfoam
maxNonOrtho         70;
maxBoundarySkewness 20;
maxInternalSkewness 4;
maxConcave          80;
minVol              -1e30;     // large negative for best layer insertion
minTetQuality       -1e30;
minTwist            0.02;
minDeterminant      0.001;     // reduce/negate for fine BLs
minFaceWeight       0.05;      // reduce for absolute sizes
minVolRatio         0.01;      // reduce for very fine BLs
minTriangleTwist    -1;
```

**`snapControls` (rarely the cause of layer problems):**

```openfoam
nSmoothPatch        3;
tolerance           2.0;
nSolveIter          50;
nRelaxIter          5;
nFeatureSnapIter    10;
implicitFeatureSnap false;
explicitFeatureSnap true;
```

The "improved" snap values (`nSmoothPatch 10`, `nSolveIter 100`, `nRelaxIter 10`, `nFeatureSnapIter 100`) help some complex geometries but are usually unnecessary for layers.

## Quick reference

1. Split castellation/snap from layer addition into two passes.
2. Use `finalLayerThickness` with `relativeSizes true` as the default.
3. Plan with a geometric-progression spreadsheet — predict near-wall distance and AR before running.
4. AR ≈ 100 is the collapse threshold; if predicted AR approaches it, reduce layers or refine the surface.
5. Finer surface meshes are the real fix; relaxing quality metrics is a workaround.
6. Identify the failing metric from the log and relax it selectively — `minDeterminant` (relative) or `minFaceWeight` (absolute) first.
7. `nLayerIter 1` disables all quality checks — debugging only.
8. Background refinement gives fine surface resolution without excessive cell count.
9. Limit refinement level jumps across a surface to at most 2.
10. Edge refinement levels do not count for layer calculations — only surface and region levels.
11. Always inspect coverage visually; the log percentage alone is not enough.
12. Accept small defects at non-critical features (trailing edges); fix them at critical ones (leading edges).
