---
title: Patch creation and boundary conditions
topic: patches-bcs
keywords: [autoPatch, surfaceToPatch, createPatch, createPatchDict, boundary file, base type, numerical type, foamDictionary, sed, inGroups, patch renaming, zero-faced patch, empty patch, wall, symmetry, slip, inlet, outlet, inletOutlet, fixedValue, zeroGradient, kqRWallFunction, omegaWallFunction, nutkWallFunction, external aerodynamics, ground plane, wall functions, backflow, fixed outlet pressure]
see_also: [snappyhexmeshdict-reference.md, geometry-preparation.md, boundary-layers.md, refinement-control.md, 2d-meshing.md]
source: Mixing-elbow and Ahmed-body practical cases (OpenFOAM v2412)
---

# Patch creation and boundary conditions

After meshing, patches sometimes need to be created, split, merged, renamed, or retyped before the case will run. This document covers the patch-manipulation utilities and the boundary-condition combinations for common flow types.

## Creating patches from surfaces

If the geometry was a single STL with no named regions, the whole body becomes one patch and you must subdivide it (e.g. to set different inlet/outlet/wall BCs).

### `surfaceToPatch` (preferred)

Creates a patch from a surface (STL), applied **during snapping**. The robust approach is to load each desired patch as a separate STL surface and apply `surfaceToPatch` **sequentially**, one surface at a time — giving exact, predictable control over which faces become which patch, without the angle ambiguity of `autoPatch`. The `-tol` option sets the matching tolerance between mesh faces and the surface.

```bash
surfaceToPatch -tol 0.001 inlet.stl
surfaceToPatch -tol 0.001 outlet.stl
```

Loosen `-tol` if faces are missed; tighten it if neighbouring faces are wrongly captured.

### `autoPatch`

Splits an existing patch by the angle between adjacent faces; faces separated by more than the threshold go to different patches.

```bash
autoPatch 75 -overwrite      # 75° feature-angle threshold
```

New patches are named `auto0`, `auto1`, … in detection order — rename them afterwards (below). `autoPatch` does **not** run in parallel; for parallel cases reconstruct first, run it serially, then re-decompose. It is convenient but less predictable than sequential `surfaceToPatch`, because the angle criterion can merge or split surfaces unexpectedly on complex geometry.

### `createPatch`

Reads `system/createPatchDict` to create, combine, or **remove zero-faced/empty patches** left over from the background mesh or baffle operations. Use it to delete leftover empty patches so the case is clean, and to merge patches (e.g. fold an overlay-refinement patch back into the parent wall — see `refinement-control.md`).

```bash
createPatch -overwrite
```

## Renaming and retyping patches

Patch **base type** lives in `constant/polyMesh/boundary`; the **numerical type** lives in each `0/` field file. Both must be set and must agree, and patch names must match between the two.

Edit the boundary file programmatically (do not hand-edit `nFaces`/`startFace`):

```bash
# Rename a patch and set its base type
foamDictionary constant/polyMesh/boundary -entry entry0/auto0/type -set patch
foamDictionary constant/polyMesh/boundary -entry entry0/inlet/inGroups -remove
foamDictionary constant/polyMesh/boundary -entry entry0/inlet/inGroups -add '1(inlet)'
```

`sed` works for bulk renaming when scripting many patches. After changing the boundary file, update every `0/` field file so the numerical type on each patch is compatible with its new base type (e.g. a `wall` base type can carry `fixedValue`/`noSlip`/wall-function numerical types; a `patch` base type cannot carry `empty`). Removing or adding `inGroups` keeps ParaView/patch-group selections tidy.

## Boundary base types vs numerical types

The **base type** is the physical/topological nature of the patch (`wall`, `patch`, `empty`, `symmetry`, `symmetryPlane`, `cyclic`, `cyclicAMI`, …). The **numerical type** is the condition applied to a field on that patch (`fixedValue`, `zeroGradient`, `inletOutlet`, `noSlip`, `slip`, `kqRWallFunction`, …). Constraints: an `empty` base type forces `empty` on every field (2D slabs); `wall` is required for wall-function numerical types; `symmetry`/`symmetryPlane` and `cyclic` similarly constrain their fields. Mismatches are a common run-time error.

---

## Boundary conditions for external aerodynamics

A typical external-flow setup (flow over a body in a box) with a steady RANS solver:

**Inlet** (`patch`): velocity `fixedValue` (uniform freestream); pressure `zeroGradient`; turbulence `fixedValue` (k, ω/ε from freestream intensity and length scale).

**Outlet** (`patch`): velocity `inletOutlet` (zeroGradient on outflow, fixedValue=0 on any backflow); **pressure `fixedValue` = 0**; turbulence `inletOutlet`.

**Ground plane** (`wall`): `slip` if it should not develop a boundary layer (inviscid wall), or `fixedValue`/`noSlip` with wall functions if a ground boundary layer matters (e.g. ride-height-sensitive cases).

**Side and top** (`patch` or `symmetry`): `symmetry` for a planar far boundary aligned with the flow; `slip` for a curved or angled far boundary (symmetry requires a planar patch and fails on curved ones).

**Body** (`wall`): velocity `fixedValue` = (0 0 0) (`noSlip`); pressure `zeroGradient`; turbulence wall functions — `kqRWallFunction` (k), `omegaWallFunction` (ω), `nutkWallFunction` (ν_t), or the ε-equivalents.

### Two BC choices that cause subtle failures

- **`inletOutlet` on the outlet is essential for stability.** Without it, any recirculation/backflow at the outlet (common in separated wakes) injects unphysical velocity and the run diverges. `inletOutlet` switches to `zeroGradient` on outflow and clamps to the `inletValue` on inflow.
- **The outlet pressure must be a fixed reference (`fixedValue` = 0).** If the outlet pressure is left `zeroGradient`, the whole field has no absolute reference: the **velocity field oscillates even though residuals look converged**. Always pin the outlet pressure and **verify the velocity field visually** — normal-looking residuals do not guarantee a converged velocity field.

### Ground-plane refinement

Refine the body–ground gap with a `searchablePlane` (the ground) plus distance-based `refinementRegions`, or a thin body-of-influence box spanning the gap, so the near-ground flow is resolved without over-refining elsewhere. See `refinement-control.md`.

### Wall modelling vs wall resolving

- **Wall modelling:** y⁺ ≈ 30–60, ~3 boundary layers, standard wall functions. Cheaper; the right starting point for setup and validation.
- **Wall resolving:** y⁺ < 5 (ideally < 1), ~5–6 extra layers and often 2–3 more surface refinement levels — a large increase in cell count and memory. Reserve for cases where near-wall physics (transition, fine separation, heat transfer) must be captured. See `boundary-layers.md`.

## Internal flows (pipes, vessels)

Inlet velocity `fixedValue` / pressure `zeroGradient`; outlet velocity `inletOutlet` or `zeroGradient` / pressure `fixedValue`; walls `noSlip` with wall functions. The same outlet-pressure-reference caution applies. Internal flows benefit from uniform interior refinement so the boundary layer grows cleanly on a uniform surface mesh (see `refinement-control.md`).
