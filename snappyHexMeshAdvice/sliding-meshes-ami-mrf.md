---
title: Sliding meshes, AMI and MRF
topic: rotating-machinery
keywords: [sliding mesh, AMI, cyclicAMI, cyclicACMI, MRF, MRFProperties, createBaffles, splitBaffles, createBafflesDict, cellZone, faceZone, inner_volume, dynamicMeshDict, dynamicMotionSolverFvMesh, solidBody, rotatingMotion, multiSolidBodyMotionFvMesh, moveDynamicMesh, checkAMI, AMI weights, movingWallVelocity, rotatingWallVelocity, lowWeightCorrection, interface resolution, pimpleFoam, simpleFoam, splitMeshRegions, createPatch]
see_also: [snappyhexmeshdict-reference.md, geometry-preparation.md, mesh-quality-and-checkmesh.md, refinement-control.md]
source: OpenFOAM sliding-meshes tutorial; CSTR practical case (OpenFOAM v2412)
---

# Sliding meshes, AMI and MRF

For rotating geometry, the solution must be coupled between a moving (rotating) region and a fixed region. Two approaches:

- **Sliding mesh** — the rotating region physically moves each time step; the regions are topologically separated and coupled across an **arbitrary mesh interface (AMI)**, patch type `cyclicAMI`. Intrinsically unsteady; the geometry must have axial symmetry. Transient solver: `pimpleFoam` (dynamic-mesh support is built in — no separate solver needed).
- **MRF (Multiple Reference Frame)** — the mesh stays fixed; rotation enters as source terms within the rotating `cellZone`. Runs steady or unsteady, and is much faster, so it is attractive whenever a steady approximation is acceptable. Steady solver: `simpleFoam`.

The key meshing difference: sliding mesh needs the mesh **split into separate regions**; MRF needs only the `cellZone` (no split, no AMI patches).

## AMI fundamentals

AMI couples non-matching patches by **area-weighted interpolation**: each face takes contributions from partially overlapping faces on the neighbour patch, weighted by intersecting area. For each face the weights should sum to ~1; where geometries match poorly the sum deviates and conservation errors appear. **To minimise interpolation error, the meshes on the two sides of the interface must be of similar resolution.** A finer rotating side against a coarser fixed side introduces interpolation error.

`cyclicACMI` is a variant for **partially overlapping** patches, blending the AMI coupling with a secondary patch type (e.g. a wall). AMI is not limited to rotation — it works for any dynamic-mesh case needing interpolation between fixed and moving patches, and for static non-conformal interfaces (e.g. coupling non-matching periodic boundaries in sector geometries).

`transform` describes how to map the neighbour onto the owner: `noOrdering` (no specific mapping) or `coincidentFullMatch` (no transform, with a face-match check). `lowWeightCorrection` handles faces with low weight sums near the overlap edge:

```openfoam
AMI1 { type cyclicAMI; neighbourPatch AMI2; transform noOrdering; lowWeightCorrection 0.2; }
```

## Match interface resolution

Ensure the interface surface (the faceZone) has the **same refinement level on both sides**. In `snappyHexMeshDict`, give the `inner_volume` surface (which defines the interface) the same level as the surrounding volume mesh there — e.g. `level (1 1)` matching the background. A resolution mismatch shows up as poor AMI weights and interpolation error.

## Creating the zones during meshing

The `cellZone` and `faceZone` are created in `castellatedMeshControls` from a surface (here `inner_volume`, an STL of the cylindrical rotating region) referenced in `refinementSurfaces`:

```openfoam
refinementSurfaces
{
    inner_volume
    {
        level (1 1);
        cellZone        cell_inner_volume;
        faceZone        face_inner_volume;
        faceType        internal;          // keep interface faces internal (default)
        cellZoneInside  insidePoint;
        insidePoint     (50 0 100);        // must lie inside the inner_volume surface
    }
}
```

`insidePoint` must be inside the `inner_volume` geometry. After meshing, `checkMesh` reports **one** region — already valid for **MRF**. For **sliding meshes** the region must be topologically split (next). Multiple rotating bodies: add more entries (`inner_volume1`, `inner_volume2`) in both `geometry` and `refinementSurfaces`.

Geometry prep: split the shaft at the interface so the inside portion rotates and the outside stays fixed — export the two parts as separate STLs. See `geometry-preparation.md`.

## Splitting into regions for sliding meshes

Two compulsory steps after meshing:

```bash
createBaffles -overwrite
splitBaffles  -overwrite
```

- **`createBaffles`** reads `system/createBafflesDict` and duplicates the internal faceZone faces into two `cyclicAMI` patches (`AMI1`, `AMI2`). Two regions now exist but are still stitched through the patches.
- **`splitBaffles`** removes the shared points so the regions can move independently. `checkMesh` now reports **two** regions — ready for sliding mesh.

`createBafflesDict`:

```openfoam
baffles
{
    rotating
    {
        type     faceZone;
        zoneName face_inner_volume;       // the faceZone from snappyHexMeshDict
        patches
        {
            master { name AMI1; type cyclicAMI; matchTolerance 0.0001; neighbourPatch AMI2; transform noOrdering; }
            slave  { name AMI2; type cyclicAMI; matchTolerance 0.0001; neighbourPatch AMI1; transform noOrdering; }
        }
    }
}
```

For multiple interfaces, run `createBaffles`/`splitBaffles` for each, and create all the required `cellZone`s and `cyclicAMI` patches at meshing time.

### Optional cleanup

```bash
createPatch -overwrite                       # remove zero-faced patches left from the background mesh
splitMeshRegions -detectOnly                 # report region names without modifying the mesh
transformPoints 'scale=(0.01 0.01 0.01)'     # e.g. mm → m if needed
```

Verify the final mesh reports `Number of regions: 2`. In `paraFoam`, enable **Include Zones** to view `AMI1`, `AMI2`, `cell_inner_volume`, etc.

## Boundary conditions

On AMI patches, every field uses `type cyclicAMI` — set automatically by `createBaffles`, so no manual BC setup is needed there:

```openfoam
"(AMI1|AMI2)" { type cyclicAMI; value $internalField; }
```

For physical walls in the rotating zone: `movingWallVelocity` for the impeller (moves with the mesh) and `rotatingWallVelocity` for the shaft (fixed patch with imposed rotation — specify origin, axis, angular velocity).

## Checking AMI quality

```bash
moveDynamicMesh -checkAMI -noFunctionObjects
```

This previews mesh motion and prints AMI weight statistics at each step (and saves the weight field). Weights should be as close to 1 as possible on both source and target patches:

```
AMI: Patch source sum(weights) min/max/average = 0.94746705, 1.0067199, 0.99994232
AMI: Patch target sum(weights) min/max/average = 0.94746692, 1.0004497, 0.99980782
```

Poor weights indicate resolution mismatch at the interface and will introduce interpolation error — fix by matching the two sides' refinement.

## Configuring mesh motion (`constant/dynamicMeshDict`)

Single rotating zone, solid-body rotation:

```openfoam
dynamicFvMesh    dynamicMotionSolverFvMesh;
motionSolverLibs ("libfvMotionSolvers.so");
motionSolver     solidBody;
cellZone         cell_inner_volume;

solidBodyMotionFunction rotatingMotion;
rotatingMotionCoeffs { origin (0 0 0); axis (0 0 1); omega 12.566370; }   // rad/s
```

Preview motion without solving: `moveDynamicMesh -noFunctionObjects`. Run: `pimpleFoam` (serial) or `mpirun -np 4 pimpleFoam -parallel`.

### Multiple rotating bodies

Use `multiSolidBodyMotionFvMesh`, with one sub-dictionary per `cellZone`:

```openfoam
dynamicFvMesh    multiSolidBodyMotionFvMesh;
motionSolverLibs ("libfvMotionSolvers.so");
multiSolidBodyMotionFvMeshCoeffs
{
    cell_inner_volume1 { solidBodyMotionFunction rotatingMotion; rotatingMotionCoeffs { origin (0 0 0); axis (0 0 1); omega 6.283185; } }
    cell_inner_volume2 { solidBodyMotionFunction rotatingMotion; rotatingMotionCoeffs { origin (0 0 0); axis (0 0 1); omega 6.283185; } }
}
```

Each sub-dictionary is named after its `cellZone`. Create the zones and `cyclicAMI` patches for every interface at meshing time, and run `createBaffles`/`splitBaffles` for each.

## MRF configuration (`constant/MRFProperties`)

No region split and no AMI — only the `cellZone`:

```openfoam
zone1
{
    cellZone cell_inner_volume;
    active   yes;
    nonRotatingPatches ();
    origin (0 0 0); axis (0 0 1); omega constant 12.566370;
}
```

For impeller walls use `movingWallVelocity` with value zero (MRF source terms handle rotation implicitly); `rotatingWallVelocity` for the shaft. Steady solver: `simpleFoam`.

## Parallel decomposition

`scotch` and `hierarchical` generally work well with AMI. Avoid constrained decomposition methods that conflict with AMI. Always `checkMesh` and `moveDynamicMesh -checkAMI` before the full run.
