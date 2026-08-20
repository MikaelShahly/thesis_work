---
title: Free-surface (VOF) meshing
topic: free-surface
keywords: [free surface, VOF, interFoam, waterline, setFields, staircase, face alignment, multi-block, mergePatchPairs, searchablePlane, waterline refinement, interface, alpha.water, writePrecision, small hull, mode distance, refinementRegions]
see_also: [background-mesh-and-refinement-strategies.md, refinement-control.md, geometry-preparation.md]
source: boat-hull practical case (OpenFOAM v2412)
---

# Free-surface (VOF) meshing

For free-surface (VOF, e.g. `interFoam`) cases the mesh must do two extra things well: place a clean cell **face** at the still-waterline so the initial phase field is sharp, and concentrate resolution in a band around the interface so the free surface stays sharp as it moves.

## Why a cell face must align with the waterline

`setFields` initialises the volume-fraction field (`alpha.water`) by marking cells above/below a plane. If a cell **straddles** the waterline, it is assigned a single intermediate fraction and the initial interface becomes a staircase of half-filled cells instead of a clean line. The fix is a mesh whose cell **faces** coincide with the still-waterline, so every cell is cleanly full or empty at t = 0.

## Build the aligned face with a multi-block background mesh

Split the `blockMeshDict` into two blocks stacked in z, sharing an interface at the waterline height `zmid`, and merge them with `mergePatchPairs`. The shared face sits exactly at the waterline; vertical spacing can differ above and below (finer near the surface). Full `blockMeshDict` pattern is in `background-mesh-and-refinement-strategies.md`.

```openfoam
zmid 0;                 // still-water level
blocks
(
    hex (0 1 2 3 4 5 6 7)      ($xc $yc $zc_lower) simpleGrading (1 1 1)
    hex (8 9 10 11 12 13 14 15) ($xc $yc $zc_upper) simpleGrading (1 1 1)
);
mergePatchPairs ( (interface_lower interface_upper) );
```

`snappyHexMesh` then refines from this background as usual; the aligned face is preserved through castellation provided refinement transitions are kept away from the waterline band.

## Refine a band around the waterline with a searchablePlane

Add the waterline as a `searchablePlane` and refine within a distance of it with `mode distance`. Because `distance` refines on **both** sides of the plane, a distance of 0.05 produces a refined band of total height ~0.1 centred on the waterline — exactly what a sharp interface needs.

```openfoam
geometry
{
    waterline
    {
        type searchablePlane; planeType pointAndNormal;
        pointAndNormalDict { basePoint (0 0 0); normalVector (0 0 1); }
    }
}
refinementRegions
{
    waterline { mode distance; levels ((0.05 4)); }   // ~0.1 tall refined band
}
```

For a moving/large-amplitude free surface, widen the band (larger distance) or stack distance bands (`levels ((0.05 5) (0.15 4) (0.3 3))`) so the surface stays inside the fine region throughout its motion.

## Separate STL surfaces: use refinementRegions, not refinementSurfaces

When the waterline (or any auxiliary plane/surface loaded only to drive refinement) is a separate entity from the hull, drive its refinement through `refinementRegions` (`mode distance`/`inside`), **not** `refinementSurfaces`. Putting it in `refinementSurfaces` would create an extra patch at the intersection and break boundary-layer growth on the hull. `refinementSurfaces` should list only the hull (and any regions embedded in the hull's own STL/OBJ). See `refinement-control.md`.

## Small hulls: write precision

Model-scale hulls have small cells near the waterline and at the bow/stern. Raise precision and use binary so small dimensions are not truncated:

```openfoam
// system/controlDict
writeFormat     binary;
writePrecision  12;
```

Binary writes are smaller and preserve small geometric features (especially at refinement transitions) better than ASCII. Alternatively scale the geometry up before meshing. Keep `snappyHexMeshDict::mergeTolerance` smaller than the write tolerance implied by `writePrecision` (see `geometry-preparation.md`).

## Checklist

1. Two-block `blockMeshDict` with the shared face at the waterline; `mergePatchPairs`.
2. `searchablePlane` waterline + `mode distance` refinement band around it.
3. Auxiliary surfaces driven through `refinementRegions`, never `refinementSurfaces`.
4. `writePrecision 12`, `writeFormat binary` for model-scale hulls.
5. Keep refinement transitions out of the waterline band so the aligned face survives.
6. After meshing, confirm with `setFields` + ParaView that the initial `alpha.water` interface is a clean line, not a staircase.
