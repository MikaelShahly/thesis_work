---
title: 2D meshing with extrudeMesh
topic: 2d-meshing
keywords: [2D, extrudeMesh, extrudeMeshDict, empty patch, linearNormal, single cell thick, slab, implicit feature snap, force coefficients, thickness 1, maxZ, minZ, nLayers 1]
see_also: [snappyhexmesh-workflow.md, snappyhexmeshdict-reference.md, boundary-layers-at-sharp-edges.md]
source: NACA0012 and A2-wedge practical cases (OpenFOAM v2412)
---

# 2D meshing with extrudeMesh

`snappyHexMesh` is a 3D mesher, so a 2D mesh is produced by meshing a thin 3D slab and collapsing it to a single cell in depth with `extrudeMesh`.

## Workflow

1. Build a 3D background mesh with `blockMesh`, **one cell thick in z**.
2. Run `snappyHexMesh` in 3D (`-overwrite`).
3. `checkMesh` the 3D result.
4. `extrudeMesh` to produce the single-layer 2D mesh.
5. `checkMesh` the 2D result.
6. `createPatch` for patch renaming/typing.

```bash
foamCleanTutorials
blockMesh
snappyHexMesh -overwrite
extrudeMesh
checkMesh -latestTime
```

`extrudeMesh` projects one lateral face onto its mirror face, so the two side faces of the slab must be parallel and the **background mesh width must match the geometry width exactly**. If the geometry is wider than the background mesh, it is cut by the lateral faces. The two lateral patches (front/back of the slab) must be type `empty`.

## extrudeMeshDict

```openfoam
constructFrom     patch;
sourceCase        ".";
sourcePatches     (maxZ);
exposedPatchName  minZ;
flipNormals       false;

extrudeModel      linearNormal;
nLayers           1;                 // must be 1 for a 2D case
linearNormalCoeffs { thickness 1; }  // strongly recommend 1

mergeFaces        false;
```

Set `nLayers 1`. Set `thickness 1` — force coefficients are computed per unit depth, so a unit thickness keeps the reference area correct.

## Feature snapping: prefer implicit for 2D

For 2D cases use **implicit** feature snapping; explicit snapping can cause alignment issues that the implicit method avoids cleanly:

```openfoam
snapControls
{
    implicitFeatureSnap     true;
    explicitFeatureSnap     false;
    multiRegionFeatureSnap  false;
}
```

With implicit snapping the mesher detects features automatically from `resolveFeatureAngle` (typically 30°), so you do **not** need `surfaceFeatureExtract` or `.eMesh` files — the `features` list in `castellatedMeshControls` can be left empty. (In 3D, explicit feature snapping is recommended instead, and the choice is more geometry-dependent — test it.)

## Virtual surfaces and coupling in 2D

The virtual-surface (synCup) technique and its `cyclicAMI` conversion fit naturally into the 2D workflow — extrude, then convert the virtual-surface patches with `foamDictionary`, running `checkMesh` after each stage to localise issues. See `boundary-layers-at-sharp-edges.md`.
