---
title: snappyHexMeshDict reference
topic: dictionary-reference
keywords: [snappyHexMeshDict, geometry, castellatedMeshControls, snapControls, addLayersControls, meshQualityControls, refinementSurfaces, refinementRegions, features, locationInMesh, nCellsBetweenLevels, resolveFeatureAngle, nFeatureSnapIter, nSolveIter, nRelaxIter, expansionRatio, finalLayerThickness, relativeSizes, featureAngle, searchableBox, searchableSphere, searchableCylinder, searchablePlane, distributedTriSurfaceMesh, debugFlags, writeFlags, boundary file, mergeTolerance]
see_also: [snappyhexmesh-workflow.md, refinement-control.md, boundary-layers.md, mesh-quality-and-checkmesh.md, geometry-preparation.md]
source: OpenFOAM Meshing Tutorial Lecture 2; Engys "A Comprehensive Tour of snappyHexMesh" Part 1
---

# snappyHexMeshDict reference

`snappyHexMeshDict` has five sections, each controlling one stage of the pipeline:

- `geometry` — geometry entities used for meshing (surfaces and searchable shapes).
- `castellatedMeshControls` — feature, surface, and volume refinement, plus the keep-point. All refinement happens here.
- `snapControls` — surface snapping (body-fitting).
- `addLayersControls` — boundary-layer (prismatic) meshing. No refinement happens here.
- `meshQualityControls` — quality metrics enforced continuously during meshing (may be `#include`d from a separate file such as `meshQualityDict`).

There are 70+ parameters and no GUI, which makes the dictionary intimidating, but most are rarely touched. The defaults shipped in the OpenFOAM tutorial dictionaries are robust and work in most cases. In practice the essential work is: read in the geometry, set surface refinement levels, choose which surfaces get layers, and choose how many layers.

Three boolean switches at the top select which stages run:

```openfoam
castellatedMesh    true;
snap               true;
addLayers          false;   // e.g. body-fitted mesh with no boundary layer
```

---

## geometry

STL is read in here (always from `constant/triSurface`). Multiple files are allowed. Searchable primitives (box, sphere, cylinder, plane, plate) can also be defined and used for refinement, zones, or baffles. If a surface is given no `name`, it takes the STL file name. To list the available geometry types, deliberately misspell `type` — the mesher prints the valid options.

```openfoam
geometry
{
    wolf
    {
        type    triSurfaceMesh;
        file    "wolfExtruded.stl";
        regions
        {
            wolflocal { name wolf_wall; }   // rename an STL region to a final patch name
        }
    }

    box    { type searchableBox;    min (-100 -120 -50); max (100 120 150); }
    sphere { type searchableSphere; centre (120 -100 50); radius 40; }
    cyl    { type searchableCylinder; point1 (0 0 0); point2 (1 0 0); radius 0.1; }

    plane
    {
        type searchablePlane; planeType pointAndNormal;
        pointAndNormalDict { basePoint (0 0 0); normalVector (0 1 0); }
    }
    plate  { type searchablePlate; origin (0 0 0); span (0.5 0.5 0); }
}
```

The `regions` sub-dictionary is used when an STL contains multiple named patches; each region name (as defined in the STL/OBJ) maps to a final patch name via `name`.

### Parallel memory: `distributedTriSurfaceMesh`

`triSurfaceMesh` stores the whole surface on every processor. For very large surfaces in parallel, `distributedTriSurfaceMesh` stores a partitioned triangulation and usually uses far less memory. Distribution methods: `independent` (best memory balance), `follow` (distributes by mesh bounding box to cut communication), `frozen` (unchanged). Decompose the surface first with `surfaceRedistributePar`. It tends to work better with `hierarchical` decomposition, though `scotch` is sometimes equally good. Limits of the option are not fully characterised, so test it.

```openfoam
geomB.stl { type distributedTriSurfaceMesh; distributionType follow; name geomB; }
```

### Surface collections

Complex shapes can be assembled from transformed basic shapes via `searchableSurfaceCollection` (with `mergeSubRegions` to merge sub-regions), each member taking a `scale` and a `transform`/`coordinateSystem`.

---

## castellatedMeshControls

```openfoam
castellatedMeshControls
{
    maxLocalCells       100000;
    maxGlobalCells      2000000;
    minRefinementCells  0;
    maxLoadUnbalance    0.10;
    nCellsBetweenLevels 3;

    features ( { file "wolf.eMesh"; levels ((0 2)); } );

    refinementSurfaces { /* see below */ }
    resolveFeatureAngle 30;
    planarAngle         30;
    refinementRegions   { /* see below */ }

    locationInMesh (-100 0 50);
    allowFreeStandingZoneFaces true;
}
```

**`maxGlobalCells`** — hard cap on total cells; refinement stops when reached. **`maxLocalCells`** — per-processor cap. **`minRefinementCells`** — minimum cells marked before a refinement iteration proceeds.

**`nCellsBetweenLevels`** — number of buffer cells between refinement levels. 1 is abrupt; 3 is smoother (more intermediate cells). Default 3 is generally adequate.

**`resolveFeatureAngle`** — curvature/feature refinement threshold. When the angle between adjacent surface-triangle normals exceeds it, cells refine toward the surface maximum level. It *also* governs feature-edge snapping. Higher values capture fewer features (e.g. 100 adds almost no curvature refinement); 30 is a good starting point — lower it to resolve more. The official release cannot use different values for curvature vs. edge detection.

**`features`** — explicit feature-edge refinement; see `refinement-control.md` for the `level` vs `levels` distinction (prefer `levels ((distance level))`).

**`refinementSurfaces`** — surface refinement; `level (min max)`. Min level is always applied, max is used in high curvature or where `resolveFeatureAngle` triggers. Supports POSIX regex on region names, `patchInfo { type wall|patch; }`, and cell/face-zone creation:

```openfoam
refinementSurfaces
{
    flange
    {
        level (2 3);
        patchInfo { type wall; }
        regions { "*.inlet|*.outlet" { level (3 4); } }
    }
    sphere                              // zone creation (MRF / sliding mesh / source terms)
    {
        level (1 1);
        faceZone        face_inner;
        cellZone        cell_inner;
        cellZoneInside  inside;         // inside | outside | insidePoint
        // insidePoint  (50 0 100);     // required when cellZoneInside = insidePoint
        // faceType      internal;      // internal (default) | baffle | boundary
    }
}
```

`faceType` controls the created face-zone faces: `internal` keeps them internal (default), `baffle` makes baffle pairs (mesh-motion freedom), `boundary` makes free-standing boundary faces (required if layers must grow on them). See `refinement-control.md` and `sliding-meshes-ami-mrf.md`.

**`refinementRegions`** — volume refinement using a geometry entity. Modes: `inside`/`outside` (closed volume) and `distance`. Always use the tuple form `levels ((distance level))` (plural). For `inside`/`outside` the distance is ignored but must be present (e.g. `1E15`). Regions defined *within* an STL file cannot be used here.

```openfoam
refinementRegions { box { mode inside; levels ((1E15 3)); } }
```

> v2412 (openfoam.com) syntax: use `levels ((distance level))`. The bare `level N;` form is Foundation (openfoam.org) syntax and will not work in v2412. Place STL files in `constant/triSurface` (not `constant/geometry`).

**`locationInMesh`** — the keep-point. Inside the STL ⇒ internal mesh; inside the background but outside the STL ⇒ external mesh. Must sit in a pure-hex region, never in a refinement transition.

**`allowFreeStandingZoneFaces`** — `true` keeps zone faces whose owner and neighbour are the same zone (can cause quality issues when snapped); `false` removes them so face zones exist only at true zone boundaries.

---

## snapControls

```openfoam
snapControls
{
    nSmoothPatch            3;
    tolerance               2.0;
    nSolveIter              30;
    nRelaxIter              5;
    nFeatureSnapIter        10;
    implicitFeatureSnap     false;
    explicitFeatureSnap     true;
    multiRegionFeatureSnap  false;
}
```

- **`nSmoothPatch`** — pre-smoothing iterations of patch points before projection.
- **`tolerance`** — scaling factor for the max edge length used for surface attraction.
- **`nSolveIter`** — surface-displacement smoothing iterations; higher ⇒ better body-fit. Start 30; raise toward 100 if snapping is poor (slower).
- **`nRelaxIter`** — scaling-back iterations during error reduction.
- **`nFeatureSnapIter`** — feature-edge snapping iterations; raise to fix edge artefacts.
- **`implicitFeatureSnap`** — detect features by sampling the surface (no `.eMesh` needed). Recommended for 2D. See `2d-meshing.md`.
- **`explicitFeatureSnap`** — use the `.eMesh` features from `castellatedMeshControls`. Recommended for 3D.
- **`multiRegionFeatureSnap`** — improves snapping when one STL/OBJ contains multiple regions (face groups); enable alongside `explicitFeatureSnap` for multi-region geometry.

These are the most important entries in the whole dictionary and have no universal defaults — the best values are problem-dependent.

### Recommended snap values and the doubling strategy

| Parameter | Start | After one doubling | Advised max |
|---|---|---|---|
| `nSmoothPatch` | 3 | 3 | 3 |
| `tolerance` | 2.0 | 2.0 | 2.0 |
| `nSolveIter` | 30 | 50 | 100 |
| `nRelaxIter` | 5 | 10 | 20 |
| `nFeatureSnapIter` | 10 | 20 | 100 |
| `implicitFeatureSnap` | false | false | false |
| `explicitFeatureSnap` | true | true | true |

Start from the recommended values; if the mesh is poor, double the iteration parameters (`nSolveIter`, `nRelaxIter`, `nFeatureSnapIter`). Usually one doubling resolves most issues. Keep doubling toward the advised maxima if needed. **If problems persist at the maxima, the fix is more surface/edge refinement or a finer background mesh — not more iterations.**

### Snapping artefacts: troubleshooting order

When snapping produces artefacts at sharp features or edges, adjust in this order (each later step helps less and costs more):

1. **`nFeatureSnapIter`** — double it (10 → 20 → 40, max ~100). Most effective for edge artefacts.
2. **`nSolveIter`** — 50 → 100. Do not exceed 100; if it still fails the cause is insufficient surface refinement or a geometry defect.
3. **`nRelaxIter`** — 5 → 10 → 20. Each step adds significant time.
4. **`nSmoothPatch`** — 3 → 5 → 10. Above 10 tends to make things worse.

There is no guarantee any of these resolves the artefact. The most reliable fix is to go back to castellation and increase surface or edge refinement.

---

## addLayersControls

```openfoam
addLayersControls
{
    relativeSizes           true;
    expansionRatio          1.2;
    finalLayerThickness     0.5;
    minThickness            0.001;

    layers { "wolf_.*" { nSurfaceLayers 3; } }   // regex patch matching; per-patch overrides allowed

    // Advanced
    nGrow                       0;
    featureAngle                130;
    slipFeatureAngle            30;
    nSmoothSurfaceNormals       1;
    nSmoothNormals              3;
    nSmoothThickness            10;
    maxFaceThicknessRatio       0.5;
    minMedialAxisAngle          90;
    maxThicknessToMedialRatio   0.3;
    nBufferCellsNoExtrude       0;
    nLayerIter                  50;
    nRelaxedIter                20;
    nRelaxIter                  5;
}
```

- **`layers`** — patches to receive layers and how many (`nSurfaceLayers`). Each patch must exist from `geometry`/snapping. `expansionRatio`, `finalLayerThickness`, `minThickness` can be overridden per patch.
- **`relativeSizes`** — `true`: thickness parameters are fractions of the adjacent cell; `false`: absolute metres. Relative is the recommended default. See `boundary-layers.md`.
- **`finalLayerThickness`** — outermost layer height as a fraction of adjacent surface spacing ΔS (when relative). 0.5 is a good start.
- **`expansionRatio`** — height ratio between consecutive layers.
- **`minThickness`** — layers thinner than this collapse. Set small (e.g. `0.0001`); too large silently produces 0% coverage.
- **`featureAngle`** — angle above which layers collapse automatically. One of the most important layer parameters. 130 start; 330 forces layers around convex/concave edges; 0 disables inflation.
- **Medial-axis controls** — `minMedialAxisAngle`, `maxThicknessToMedialRatio` (0.3 conservative, up to ~0.6 in narrow regions) reduce layer thickness where opposing walls are close.
- **`maxFaceThicknessRatio`** — terminates layers on warped faces.
- **`nLayerIter`** — max layer-addition iterations. After `nRelaxedIter`, the relaxed quality set is used. Setting `nLayerIter 1` disables all quality iteration (debugging only). See `boundary-layers.md`.

Layer-quality doubling strategy (these control quality/relaxation, *not* the actual layer thickness — `expansionRatio`/`finalLayerThickness`/`nSurfaceLayers` matter more for resolution):

| Parameter | Start | Advised max |
|---|---|---|
| `featureAngle` | 130 | 330 |
| `maxFaceThicknessRatio` | 0.5 | 1 |

---

## meshQualityControls

Quality is monitored continuously: any motion or topology change that creates a poor cell/face is undone, reverting to the last valid state. Full metric definitions, formulas, default vs. practical thresholds, and relative importance are in `mesh-quality-and-checkmesh.md`. A typical block:

```openfoam
meshQualityControls
{
    maxNonOrtho         75;
    maxBoundarySkewness 20;
    maxInternalSkewness 4;
    maxConcave          80;
    minVol              1e-13;
    minTetQuality       -1e30;   // large negative ⇒ best for layer insertion
    minTwist            0.02;
    minDeterminant      0.001;   // reduce/negate to restore boundary-layer coverage
    minFaceWeight       0.05;    // reduce for absolute-size layers
    minVolRatio         0.01;    // reduce for very fine boundary layers
    minTriangleTwist    -1;
    nSmoothScale        4;
    errorReduction      0.75;
    relaxed { maxNonOrtho 75; }  // looser limits used during final layer iterations
}
```

---

## Debug and write flags

Optional, commented out by default. Useful for diagnosing each stage:

```openfoam
debugFlags  ( mesh intersections featureSeeds attraction layerInfo );
writeFlags  ( scalarLevels layerSets layerFields );
```

`debugFlags mesh` saves the mesh at every internal iteration (many time directories) for step-by-step animation in ParaView — slow and disk-heavy but invaluable when other approaches fail. `writeFlags layerFields` writes a per-cell boundary-layer-coverage `volScalarField`, the best way to see exactly where layers collapsed.

---

## mergeTolerance

At the bottom of the dictionary, `mergeTolerance` sets the distance below which close entities are merged (template default `1e-8`). It must stay **smaller** than the write tolerance implied by `controlDict::writePrecision` (e.g. `writePrecision 12` ⇒ keep `mergeTolerance` below `1e-12`–`1e-5`). Raising it (e.g. to `1e-5`) can close small visual gaps but may erroneously merge intentionally-close features — increase conservatively and test. See `boundary-layers-at-sharp-edges.md`.

---

## The constant/polyMesh/boundary file

Generated automatically after meshing. It records each patch's **base type** (`wall`, `patch`, `empty`, `symmetry`, …), `nFaces`, and `startFace`. The base type is the physical patch on which a **numerical type** (set in the `0/` field files) is applied; the two must be compatible and patch names must match between `boundary` and the field files.

```openfoam
wolf  { type wall; inGroups 1(wall); nFaces 400; startFace 502679; }
```

`nFaces`/`startFace` are computed during meshing — do not edit unless you understand them. Patch names and base types may be changed (avoid special characters/whitespace); e.g. a `wall` patch can be retyped to `patch`. Rename patches and set types programmatically with `foamDictionary`/`sed` — see `patches-and-boundary-conditions.md`.
