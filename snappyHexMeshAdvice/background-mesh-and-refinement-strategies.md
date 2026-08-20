---
title: Background mesh and refinement strategies
topic: background-mesh
keywords: [blockMesh, blockMeshDict, background mesh, base mesh, simpleGrading, mergePatchPairs, uniform background, stretching, grading, topoSet, refineMesh, refineMeshDict, background refinement, searchableBox pre-refinement, two-pass, snappyHexMeshDict_block, cellLevel, pointLevel, level0Edge, surfaceIndex, restart inconsistency, multi-block, zmid, free surface alignment, cell size arithmetic, M1 M2 M3 M4]
see_also: [snappyhexmesh-workflow.md, refinement-control.md, boundary-layers.md, free-surface-vof-meshing.md]
source: Engys "Comprehensive Tour" Part 1; OpenFOAM Meshing Lecture 1; NACA0012, sphere and boat-hull practical cases
---

# Background mesh and refinement strategies

The background (base) mesh is the foundation for everything `snappyHexMesh` does. Its local cell size *next to the surface* sets the achievable surface mesh quality, curvature resolution, and boundary-layer behaviour — often more than the surface refinement level does. Refining the background mesh locally near the body is frequently cheaper and more effective than raising surface refinement levels.

## Requirements for the background mesh

- Pure hexahedra where refinement will occur.
- Cell aspect ratio ≈ 1, at least near the geometry.
- At least one cell edge intersecting the surface; more intersections give better results.
- Align with the geometry where practical.

## blockMesh

`blockMesh` builds simple block-structured hex meshes from `system/blockMeshDict`. It does not run in parallel. Each block has 8 vertices and 12 edges in the standard OpenFOAM ordering. The dictionary has five sections: `vertices`, `blocks`, `edges`, `boundary`, `mergePatchPairs`.

```openfoam
scale 1.0;          // scale factor on all coords; final mesh is always in metres

vertices ( (0 0 -0.038) (0.038 0 -0.038) ... );

blocks
(
    // hex(8 vertices) (nx ny nz) simpleGrading (ex ey ez)
    hex (0 1 4 3 9 10 13 12) (20 400 1) simpleGrading (8 8 1)
);

edges ();           // any edge not listed is straight; arc and spline available

boundary
(
    ffminy { type wall;  faces ( (0 1 10 9) (1 2 11 10) ); }
    frontAndBack { type empty; faces ( (0 3 4 1) ... ); }
);

mergePatchPairs ();
```

`simpleGrading (ex ey ez)` takes one expansion ratio per direction, defined as last-cell/first-cell size (Δ_last/Δ_first). Boundary face vertex ordering follows the right-hand rule so the normal points out of the block. `mergePatchPairs` merges separate blocks into one mesh; blocks that share vertices and are not listed are assumed one-to-one connected.

Parameterise the dictionary so only domain bounds and spacing need editing:

```openfoam
xmin -10; xmax 20; ymin -10; ymax 10; zmin 0; zmax 1;
dx 0.5; xcells #calc "abs(($xmax - $xmin)/$dx)";
dy 0.5; ycells #calc "abs(($ymax - $ymin)/$dy)";
zcells 1;
```

## Background mesh sizing

For **internal flows**, make the background domain slightly larger than the geometry (one or two cells of clearance per side) so the surface is cleanly intersected; if the box exactly matches the geometry, precision issues cause surface-cutting artefacts. An oversized box wastes cells that castellation will remove. Matching block faces to inlets/outlets can save cells but risks cutting geometry features at the boundary.

For **external flows**, size the far field for the physics (wake length, blockage) and keep the region around the body uniform.

## Four strategies for fine cells near the body (M1–M4)

All four can reach the same surface resolution; they differ in cost and control. The examples assume the same surface refinement level and layer parameters.

**M1 — Uniform background.** Constant spacing everywhere. Simplest, but resolves curvature poorly at low surface refinement; reaching good curvature needs high surface levels (6–8), which is expensive in memory and time.

**M2 — Graded background.** Add `simpleGrading` so cells are fine at the centre and coarse at the far field. Gives fine near-body cells without a uniform fine mesh. Multi-section grading example:

```openfoam
simpleGrading
(
    ( (0.3 0.2 0.1) (0.1 0.3 1) (0.6 0.5 10) )   // x
    ( (0.45 0.3 0.0588) (0.1 0.4 1) (0.45 0.3 17) ) // y
    1                                            // z
)
```

Grading is fiddly for complex geometries. **Keep uniform spacing in the region where the body sits.**

**M3 — `topoSet` + `refineMesh`.** Start uniform, then select rectangular regions (`boxToCell`) and refine them directionally. Each `topoSet`/`refineMesh` pair adds one level; nest progressively smaller boxes for cascaded refinement.

```openfoam
// refineMeshDict
set c1; coordinateSystem global;
globalCoeffs { e1 (1 0 0); e2 (0 1 0); }
directions ( e1 e2 );
useHexTopology false; geometricCut true; writeMesh false;
```

Limited to simple selection shapes (boxes, cylinders); awkward for arbitrary geometry.

**M4 — `snappyHexMesh` pre-refinement (preferred).** Run a castellation-only `snappyHexMesh` pass using searchable primitives (or an STL) to refine a region, then mesh the body in a second pass on the pre-refined background. Supports arbitrary region shapes, produces clean hex-dominant cells, and is far simpler than M3. This is the **background refinement technique** detailed next.

## Background refinement technique (the searchableBox pre-refinement)

When the required surface refinement would produce an excessively large mesh, pre-refine the background mesh only near the body, then run the main pass on it. Because all `snappyHexMesh` refinement is relative to the local background size, a refinement level on the pre-refined background reaches a much finer surface cell than the same level on the coarse background — with far fewer total cells, because only the region near the body carries the fine cells. `snappyHexMesh` memory scales with total cell count, so this is much more memory-efficient than raising surface levels globally.

### Procedure

1. Create the coarse `blockMesh` (e.g. `dx = 0.2`).
2. Write a minimal dictionary `system/snappyHexMeshDict_block`: castellation only, no body STL, only a refinement region.
3. Run it with `-overwrite` so the refined mesh replaces `constant/polyMesh`.
4. **Delete the refinement metadata files** (below), or the next run fails with a restart inconsistency.
5. Delete any time directories (e.g. `0/`) created by the refinement step.
6. Run the main `snappyHexMeshDict` on the pre-refined background.

```bash
rm *.obj > /dev/null 2>&1
rm -rf 0 > /dev/null 2>&1
foamCleanTutorials
surfaceFeatureExtract                      # for the main pass

blockMesh
snappyHexMesh -dict system/snappyHexMeshDict_block -overwrite | tee log.shm1
checkMesh -latestTime | tee log.checkmesh1

# Step 4 — remove metadata to prevent the restart inconsistency error
rm constant/polyMesh/cellLevel
rm constant/polyMesh/pointLevel
rm constant/polyMesh/level0Edge
rm constant/polyMesh/surfaceIndex          # optional but recommended

rm -rf 0 > /dev/null 2>&1                   # Step 5

snappyHexMesh -dict system/snappyHexMeshDict | tee log.shm2   # Step 6
checkMesh -latestTime | tee log.checkmesh2
```

### The `snappyHexMeshDict_block` dictionary

Castellation only; no surface geometry — only the refinement region:

```openfoam
castellatedMesh true; snap false; addLayers false;

geometry
{
    refinementBox { type searchableBox; min (-3 -3 -3); max (3 3 3); }
}

castellatedMeshControls
{
    maxLocalCells 100000; maxGlobalCells 10000000;
    minRefinementCells 0; maxLoadUnbalance 0.10; nCellsBetweenLevels 3;
    features (); refinementSurfaces {}; resolveFeatureAngle 30;

    refinementRegions
    {
        refinementBox { mode inside; levels ((1E15 1)); }  // level 1 ⇒ 0.2 → 0.1
    }
    locationInMesh (4 2 2);          // away from the box, in uniform hex
    allowFreeStandingZoneFaces true;
}

snapControls { nSmoothPatch 3; tolerance 2.0; nSolveIter 30; nRelaxIter 5;
               nFeatureSnapIter 10; implicitFeatureSnap true; explicitFeatureSnap false;
               multiRegionFeatureSnap false; }
addLayersControls {}
meshQualityControls { #include "meshQualityDict" relaxed { maxNonOrtho 75; }
                      nSmoothScale 4; errorReduction 0.75; }
mergeTolerance 1e-6;
```

Use any `searchable*` type or an STL with `mode inside`. Nest multiple boxes for cascaded refinement (outer level 1, inner level 2, …).

### Why the metadata files must be deleted

`-overwrite` writes refinement-state files into `constant/polyMesh`. If present on the next run, the mesher tries to restart from them and fails because the new dictionary differs:

```
--> FOAM FATAL ERROR:
Restarted from inconsistent cellLevel or pointLevel files.
```

(or "Number of cells in mesh does not equal size of cellLevel"). The files:

- `cellLevel`, `pointLevel` — per-cell/per-point refinement level. **Always delete; primary cause of the restart error.**
- `level0Edge` — level-0 edges; if left, the next run may add spurious refinement near the body even when not requested.
- `surfaceIndex` — which surface each face intersects; deletion optional but recommended (can cause warnings).

### Cell-size arithmetic (why this helps boundary layers)

Surface cell size at level `L` is `dx / 2^L`. With background pre-refinement multiplying the local base size, the same `L` yields a much smaller surface cell:

- No pre-refinement, `dx = 0.2`: level 2 ⇒ 0.05.
- One level of pre-refinement (0.2 → 0.1): level 2 ⇒ 0.025.
- Cascaded (0.2 → 0.1 → 0.05): level 2 ⇒ 0.0125, enabling near-wall distances of order 10⁻⁵ at comfortable aspect ratios.

Background refinement acts as a multiplier on surface refinement. A single pre-refinement level typically saves ~4–8× the cell count versus reaching the same surface resolution through higher surface levels alone. Smaller surface cells reduce the boundary-layer aspect ratio, which is the usual cause of layer collapse — see `boundary-layers.md`.

## Keep refinement transitions away from the body

The 2:1 level transition produces non-hex cells (pyramids, polyhedra). These must not overlap the region where the body is snapped and layered. Place every refinement-box transition well clear of the surface — as a rule of thumb, extend the box at least 3–5 background cell widths beyond the body in every direction (for a unit sphere on `dx = 0.2`, a box from −3 to +3). All refinement near the surface should be hex-to-hex.

`locationInMesh` (in both dictionaries) must sit in uniform hex cells, never at a transition or near a refinement-box face. A point far from the refinement region (e.g. a domain corner) is safe.

## Multi-block background for forced face alignment

When the physics needs a cell face at an exact location — a free-surface waterline, a combustion front, a reaction zone — build a multi-block `blockMeshDict` whose shared block interface sits at that height, and merge it with `mergePatchPairs`. Vertical spacing can differ above and below.

```openfoam
zmid 0;                 // the level requiring an aligned face
blocks
(
    hex (0 1 2 3 4 5 6 7)      ($xcells $ycells $zcells1) simpleGrading (1 1 1)
    hex (8 9 10 11 12 13 14 15) ($xcells $ycells $zcells2) simpleGrading (1 1 1)
);
mergePatchPairs ( (interface1 interface2) );
```

For free-surface VOF specifically, see `free-surface-vof-meshing.md`.
