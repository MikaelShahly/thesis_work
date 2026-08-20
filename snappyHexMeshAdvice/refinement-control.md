---
title: Refinement control — surface, region, edge, gap and body-of-influence
topic: refinement
keywords: [refinementSurfaces, refinementRegions, mode inside, mode outside, mode distance, levels, level, features, edge refinement, gapLevelIncrement, gapLevel, gapMode, gapSelf, body of influence, BOI, faceType, boundary, internal, baffle, surface-on-surface, 2:1 transition, nCellsBetweenLevels, curvature, one cell per 10 degrees, uniform interior refinement, surface jumping, proximity, maximum rule, resolveFeatureAngle]
see_also: [snappyhexmeshdict-reference.md, background-mesh-and-refinement-strategies.md, boundary-layers.md, geometry-preparation.md]
source: A1 cubes-and-gaps, NACA0012, mixing-elbow practical cases (OpenFOAM v2412)
---

# Refinement control — surface, region, edge, gap and body-of-influence

`snappyHexMesh` offers several overlapping mechanisms to control cell density: surface refinement, feature/edge refinement, region refinement, gap refinement, and body-of-influence refinement. This document covers each and, crucially, how they interact.

## The 2:1 transition — the property that governs everything

Each refinement level halves the cell edge (`edge = Δ / 2^n`). Transitions between levels are always 2:1: a cell's edge doubles across a level boundary, with only polyhedral transition elements (pyramids, tetrahedra) inserted between. **There is no user control over this growth rate** — it cannot be made gradual (e.g. 1.2:1). This is the single biggest limitation of the mesher and the root cause of most snapping and boundary-layer problems.

Consequences:
- At the surface, cells differ in size across a level boundary, producing a non-uniform surface mesh with varying aspect ratio. Layers grown on it then have varying aspect ratio and conflicting quality metrics → collapse.
- It injects numerical diffusion at every transition.
- For internal flows with close opposing walls, the layers from both walls interact through the transition region — particularly severe.

**Mitigations:** limit the level difference across any surface to at most two levels (e.g. 2→4, not 2→6); place transitions away from the body (see `background-mesh-and-refinement-strategies.md`); for internal flows, refine the interior uniformly (below). `nCellsBetweenLevels` widens the transition band (default 3 is generally adequate) but cannot remove the 2:1 jump.

## Surface refinement (`refinementSurfaces`)

Refines the cells the surface intersects. `level (min max)`: min always applied; max used in high curvature or where `resolveFeatureAngle` triggers. Direct and simple, but interacts poorly with feature edges and face zones when levels differ greatly from the surrounding mesh. Per-region levels and `patchInfo` are supported (see `snappyhexmeshdict-reference.md`).

## Region refinement (`refinementRegions`)

Applies a uniform level to all cells inside / outside / within a distance of a geometry. Recommended when the goal is to raise overall density around the body without large level jumps at the surface — a region with `mode inside` at a level matching or slightly above the surface level gives a clean, uniform mesh.

Modes: `inside`, `outside` (closed volumes), `distance` (within a distance of the surface — works for open surfaces and planes). Always use the tuple form:

```openfoam
refinementRegions { box { mode inside; levels ((1E15 3)); } }   // distance ignored for inside
```

> v2412 syntax: always `levels ((distance level))` (plural, tuple). The bare `level N;` is Foundation (openfoam.org) syntax and fails in v2412. For multiple distance bands, distances increasing and levels decreasing: `levels ((0.2 2) (0.4 1))`.

### Uniform interior refinement for internal flows

For internal flows, refine the whole interior uniformly with `mode inside`:

```openfoam
refinementRegions { mixing_elbow { mode inside; levels ((1E15 3)); } }
```

This removes the fast 2:1 transitions that would otherwise sit between the fine surface cells and the coarse background, which would inject numerical diffusion and wreck boundary-layer growth. Uniform interior cells give uniform surface aspect ratio, which is what lets the layers grow.

### Refinement on top of another surface — use `mode distance`, not `refinementSurfaces`

When a secondary STL (a leading-edge detail, a logo, a local "selection" patch) overlaps the main body, read it in `geometry` and refine it via `refinementRegions` with `mode distance`. **Do not put it in `refinementSurfaces`** — that creates an extra patch at the intersection, which breaks boundary-layer growth and produces faces that are hard to merge.

```openfoam
refinementRegions { leading_edge { mode distance; levels ((0.1 6)); } }
```

The primary surface stays the only patch. This is also the correct way to refine standalone auxiliary surfaces loaded only for refinement — applying refinement to them in `refinementSurfaces` produces artefacts; `refinementSurfaces` should reference only the main body and surfaces with regions embedded in the same STL/OBJ.

## Feature/edge refinement (`features`)

Refines cells along extracted `.eMesh` edges. Extraction is covered in `geometry-preparation.md`.

**Prefer the `levels` (distance-based) syntax over a single `level`.** A single `level N` reliably forces *snapping* to the edge but does **not** reliably force the cell *splitting* — `level 4` sometimes does not produce level-4 refinement. The `levels ((distance level))` form always refines correctly.

```openfoam
features
(
    { file "mixing_elbow.eMesh"; levels ((0.1 3)); }
    { file "ring.eMesh";         levels ((0.1 4) (0.2 3)); }  // distances ↑, levels ↓
);
```

List each surface's `.eMesh` separately — wildcards are not supported in `features`.

**Edge refinement does not count for boundary-layer or gap calculations.** It only sets volume density near edges. The boundary-layer algorithm uses the highest *surface*/*region* level for the effective surface cell size, not the edge level (so for surface level 4 + edge level 6, use 4 in aspect-ratio estimates). See `boundary-layers.md`.

## Curvature resolution: one cell per 10 degrees

Aim for roughly one cell per 10° of curvature: the surface edge length should be about the arc length subtended by 10° at the local radius. Because of the 2:1 transition, if the surface level gives ~10°/cell but a transition drops to the next coarser level, angular resolution jumps to 20°/cell, then 40°/cell — which is exactly why curved regions are so prone to boundary-layer collapse.

Worked sizing: for a pipe of radius 0.25 m, 10° resolution needs an edge of ~0.044 m. With background `dx = 0.2 m`, level 2 gives 0.05 m (close); a tighter small pipe needs level 3 (0.025 m).

## Gap refinement

### `gapLevelIncrement` (simple, older)

Automatic refinement in narrow gaps between surfaces. Available globally (`castellatedMeshControls`) and locally (per `refinementSurfaces` entry).

- It is a **binary switch** — any positive integer = on, 0 = off. The number is irrelevant; it always adds exactly **two** levels (`gapLevelIncrement 2` and `gapLevelIncrement 999` behave identically).
- It triggers **only when exactly one or two cells span the gap**. Three or more cells ⇒ no refinement. Re-running on an already-refined gap does nothing (now >2 cells).
- Detection is on the internally-tracked refinement level (after region refinement, before layers).
- **Local use needs two surfaces:** both bounding surfaces of the gap must enable it; enabling on one isolated surface does nothing.

```openfoam
// Global — all gaps in the domain
castellatedMeshControls { gapLevelIncrement 2; }

// Local — both opposing surfaces must enable it
refinementSurfaces
{
    body_lower   { level (1 1); gapLevelIncrement 2; }
    ground_plane { level (1 1); gapLevelIncrement 2; }
}
```

Best used as a lightweight safety net for unexpected narrow gaps. It is too inflexible (no threshold control, fixed two levels) to be a primary strategy.

### `gapLevel` / `gapMode` / `gapSelf` (controlled, v2412 — preferred)

Inside `refinementRegions`, gives real control over gap resolution. `gapLevel (numGapCells minLevel maxLevel)`:

- `numGapCells` — minimum cells wanted in the gap (usually > 3; lower may not resolve).
- `minLevel` — level at which gap detection starts.
- `maxLevel` — upper cap, to avoid runaway refinement on one stray feature.

`gapMode` — which side the algorithm works on: `inside`, `outside`, `mixed` (default). `gapSelf false` ignores gaps within the same surface (only between different surfaces).

```openfoam
refinementRegions
{
    myRegion
    {
        mode inside; levels ((1E15 0));
        gapLevel (4 0 10);   // ≥4 cells in the gap, detect from level 0, cap at level 10
        gapMode  mixed;
        gapSelf  false;
    }
}
```

Unlike `gapLevelIncrement` (which *adds* two levels on top of existing refinement), `gapLevel` refines toward an **absolute** `maxLevel`. It can be overridden per surface in `refinementSurfaces`, but the override can only restrict, never extend, the selected cells. Use it whenever specific gaps need reliable, predictable resolution.

### Fixing surface-mesh "jumping" in narrow gaps

When two surfaces are one cell apart, the snapper can jump — one body's surface mesh snaps to the *neighbouring* geometry, producing distorted or inverted cells. Enabling `gapLevelIncrement` on the two surfaces (or `gapLevel` in a region) inserts cells in the gap so the snapper can resolve both surfaces. If a surface mesh appears to jump or interpenetrate near a narrow passage, try this before anything more complex.

## Body-of-influence (BOI) refinement

A BOI is a closed surface (cylinder, box, custom STL) loaded as geometry but used only to define a refinement region — it never becomes a wall/patch. Reference it in `refinementRegions` with `mode inside`; all enclosed cells refine to the level.

```openfoam
geometry        { boi_cylinder { type triSurfaceMesh; file "boi1.stl"; } }
refinementRegions { boi_cylinder { mode inside; levels ((1E15 2)); } }
```

**BOI vs. distance-from-surface:** `mode distance` from a surface refines in all normal directions, including where you don't need it; a BOI confines refinement to the enclosed volume. For a body–ground gap, a thin BOI box/cylinder spanning the gap gives precise control; for a wake, a long BOI cylinder/wedge aligned with the flow is typical. Creating effective BOIs is manual (build in CAD, export STL to `constant/triSurface`) but gives far more precise control than any automatic gap detection.

## `faceType` and surface-on-surface refinement

An overlay STL placed on/near a wall can apply localised refinement via `refinementSurfaces` at a higher level — but `faceType` must be set correctly:

- **`internal` (default)** — faces become internal mesh faces. Breaks patch grouping and **prevents boundary-layer growth** on those faces.
- **`baffle`** — baffle pairs (coincident boundary faces sharing points). For AMI/`stitchMesh`, not for plain surface refinement; no layer growth.
- **`boundary`** — free-standing boundary faces (baffles without shared points). **Recommended for surface-on-surface refinement:** creates a proper wall patch that supports layer growth, and can be merged with the underlying wall via `createPatch`.

```openfoam
refinementSurfaces
{
    overlay_surface { level (4 4); faceZone refinement_zone; faceType boundary; }
}
```

**Prefer region refinement over surface-on-surface.** `refinementRegions` with `mode distance`/`inside` referencing the overlay achieves the same cell-size control without extra patches or face-type complications:

```openfoam
refinementRegions { overlay_surface { mode distance; levels ((0.2 4)); } }
```

(`faceType boundary` is the right choice when you specifically need a separate patch that can carry its own boundary layers — see `boundary-layers-at-sharp-edges.md`.)

## Refinement within STL regions

When one STL has multiple named solids, apply different levels and gap settings per region in a single surface entry — useful for enabling `gapLevelIncrement` only on the part near another surface (e.g. a car underbody near the ground):

```openfoam
refinementSurfaces
{
    body
    {
        level (1 1);
        regions
        {
            underbody  { level (2 2); gapLevelIncrement 2; }
            windshield { level (3 3); }
        }
    }
}
```

## How the methods interact — the maximum rule

The effective level at any cell is the **maximum** of all applicable specifications; refinement does **not** stack additively. A cell inside a level-2 BOI that is also on a level-2 surface is refined to level 2, not 4. Overlapping BOI + surface + region all collapse to the maximum.

The one exception: `gapLevelIncrement` is **additive** — it adds two levels on top of whatever level already exists at the gap (level 2 → level 4). `gapLevel` is not additive; it targets an absolute `maxLevel`.

Edge refinement (`features`) is independent: it sets volume density near edges and does not influence boundary-layer calculations or gap detection.
