---
title: Boundary layers at sharp edges — the virtual-surface technique
topic: boundary-layers-sharp
keywords: [sharp edge, trailing edge, virtual surface, synCup, faceType boundary, _slave, cyclicAMI, foamDictionary, mergeTolerance, layer collapse, right-angle junction, stilts, sequential layer addition, leading edge, wing, blade, matchTolerance, faceAreaWeightAMI]
see_also: [boundary-layers.md, refinement-control.md, geometry-preparation.md, sliding-meshes-ami-mrf.md, 2d-meshing.md]
source: A2 wedge case; Ahmed-body case (OpenFOAM v2412)
---

# Boundary layers at sharp edges — the virtual-surface technique

At a sharp trailing edge or any acute convex angle, the layers growing from the two converging surfaces collide and the mesher cannot resolve the intersection, leaving missing or distorted layers exactly where they matter. This is a recurring `snappyHexMesh` difficulty. The first line of defence is to add a fillet in CAD (see `geometry-preparation.md`); when the edge must stay sharp, use a virtual surface.

## The virtual surface (synCup)

Insert an extra surface — a *virtual surface* or *synCup* — downstream of the sharp edge, acting as a continuation of the body. The boundary layer grows along the body, passes through the trailing edge, and keeps propagating along the virtual surface, so the layers never have to close on themselves at the corner. The collision is eliminated.

The virtual surface is not a physical wall in the simulation — it is a meshing artifact. After meshing, its two sides are coupled with a `cyclicAMI` interface so flow passes through as if the faces were internal. The technique is standard in aerospace and wind energy (virtual surfaces along leading and trailing edges of wings and blades) and in structural-solver meshes.

## Implementation in snappyHexMeshDict

### Geometry

The virtual surface is a separate STL loaded alongside the body:

```openfoam
geometry
{
    wedge { type triSurfaceMesh; file "wedge.stl"; }
    tail  { type triSurfaceMesh; file "tail.stl"; }
};
```

### `faceType` decides whether layers can grow

Set `faceType` in the virtual surface's `refinementSurfaces` entry. It controls what happens to the faces created there and directly determines layer growth:

- **`boundary`** — free-standing boundary faces (baffles without shared points). Because they are boundary faces, **layers can grow on them** — this is the option the technique requires. The mesher automatically creates a companion `<name>_slave` patch (the other side).
- **`internal`** — internal mesh faces. Refinement works but **no layers** can grow.
- **`baffle`** — zero-thickness walls with shared points; mesh-motion freedom but **no layers**.

```openfoam
tail { level (4 4); faceZone face_inner; faceType boundary; }
```

**Key rule:** layers grow only on a surface with `faceType boundary`. With `internal` or `baffle`, the layer step silently skips that surface even if `nSurfaceLayers` is set for it.

### The `_slave` patch

With `faceType boundary`, `snappyHexMesh` auto-creates `<surfaceName>_slave` (e.g. `tail_slave`) — the projection/other side of the free-standing boundary. No separate STL is needed. To grow layers on **both** sides, list both in `addLayersControls`; counts and ratios can differ from the main body:

```openfoam
addLayersControls
{
    layers
    {
        "(wedge|wedgeTE)" { nSurfaceLayers 5; }
        tail        { nSurfaceLayers 3; expansionRatio 1.5; finalLayerThickness 1; }
        tail_slave  { nSurfaceLayers 3; expansionRatio 1.5; finalLayerThickness 1; }
    }
}
```

Per-surface tuning (e.g. a higher `expansionRatio` on the tail) is a practical way to control the transition from the body onto the virtual surface.

## Converting the virtual surface to a coupled interface

After meshing, `tail` and `tail_slave` are physical walls; convert them to a `cyclicAMI` pair so the solver interpolates across them. Rename/assign with `createPatch`, then set up the coupling with `foamDictionary`:

```bash
createPatch -overwrite | tee log.createPatch

foamDictionary constant/polyMesh/boundary -entry entry0/tail/type           -set cyclicAMI
foamDictionary constant/polyMesh/boundary -entry entry0/tail/inGroups        -remove
foamDictionary constant/polyMesh/boundary -entry entry0/tail/matchTolerance  -add 0.001
foamDictionary constant/polyMesh/boundary -entry entry0/tail/neighbourPatch  -add tail_slave
foamDictionary constant/polyMesh/boundary -entry entry0/tail/transform       -add noOrdering
foamDictionary constant/polyMesh/boundary -entry entry0/tail/method          -add faceAreaWeightAMI

foamDictionary constant/polyMesh/boundary -entry entry0/tail_slave/type          -set cyclicAMI
foamDictionary constant/polyMesh/boundary -entry entry0/tail_slave/inGroups       -remove
foamDictionary constant/polyMesh/boundary -entry entry0/tail_slave/matchTolerance -add 0.001
foamDictionary constant/polyMesh/boundary -entry entry0/tail_slave/neighbourPatch -add tail
foamDictionary constant/polyMesh/boundary -entry entry0/tail_slave/transform      -add noOrdering
foamDictionary constant/polyMesh/boundary -entry entry0/tail_slave/method         -add faceAreaWeightAMI
```

`matchTolerance` matters: depending on resolution you may need to loosen it (e.g. `0.0001` → `0.001`). Too tight, and interpolation fails to find matching face pairs.

The coupled patches need `cyclicAMI` type in **every** field file (pressure, velocity, turbulence, any transported scalar):

```openfoam
"(tail|tail_slave)" { type cyclicAMI; }
```

`cyclicAMI` handles the non-conformal interpolation automatically. For more on AMI, see `sliding-meshes-ami-mrf.md`.

## The small gap at the junction — accept it

A very small gap often appears where the body meets the virtual surface: numerical precision in snapping and layer addition means the two sets of layers don't close to machine precision. In practice this is not a problem — it's within mesh tolerance, `cyclicAMI` interpolates smoothly across it, continuity errors stay well-behaved, and the solution shows no artefacts. Treat these as cosmetic, not functional. Diagnose with:

```bash
checkMesh -allGeometry -writeSets -writeSurfaces -allTopology
```

Near-points clustering around the virtual surface and symmetry planes are expected and benign.

### Closing the gap with `mergeTolerance` (optional)

`mergeTolerance` at the bottom of `snappyHexMeshDict` (template default `1e-8`) merges entities closer than the threshold. Raising it (e.g. `1e-5`) can close the visual gap:

```openfoam
mergeTolerance 1e-5;
```

Caveats: it must stay **smaller** than the `controlDict::writePrecision` tolerance (standard pairing `mergeTolerance 1e-8` with `writePrecision 12`); raising it too far can erroneously merge intentionally-close features. Start at `1e-8`, increase only if you see gap issues, and test on your geometry.

## Right-angle junctions (e.g. supports meeting a ground plane)

Where two surfaces meet at a right angle — a support stilt on a ground plane — the layers from both collide and quality enforcement collapses them. Two mitigations:

**Sequential layer addition.** Mesh and layer the body *without* the second surface first, then add that surface (and its layers) in a second pass. Adding the stilt layers separately avoids the junction collision. The junction isn't perfect but is much better than doing both at once.

**Local refinement at the junction.** Finer refinement around both surfaces near the junction shrinks the cells at the collision point, improving aspect ratio so more quality metrics pass — use distance-based `refinementRegions`. See `refinement-control.md`.

Small layer defects at such junctions are generally acceptable and do not significantly affect the solution on the main body.

## Complete 2D example workflow

For the wedge case (2D, extruded), the full sequence interleaves meshing, extrusion, coupling, and repeated `checkMesh` to isolate where any issue is introduced:

```bash
foamCleanTutorials
blockMesh
snappyHexMesh -overwrite | tee log.shm
checkMesh -latestTime | tee log.checkmesh3D
extrudeMesh
checkMesh -latestTime | tee log.checkmesh2D
createPatch -overwrite | tee log.createPatch
# ... foamDictionary cyclicAMI conversion for tail / tail_slave (as above) ...
checkMesh -allGeometry -writeSets -writeSurfaces -allTopology
```

Run `checkMesh` at multiple stages (after 3D meshing, after extrusion, after coupling) and keep every log (`tee log.<step>`) so quality issues can be traced to the stage that introduced them. For the 2D extrusion workflow itself, see `2d-meshing.md`.
