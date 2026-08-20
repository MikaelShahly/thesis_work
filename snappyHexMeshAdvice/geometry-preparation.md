---
title: Geometry preparation
topic: geometry-prep
keywords: [STL, OBJ, surfaceTransformPoints, surfaceMeshTriangulate, face groups, MeshMixer, Inspector, normals, surfaceCheck, surfaceOrient, watertight, closed solid, multi-body assembly, triangulation, remesh, fillets, writePrecision, binary, surfaceFeatureExtract, surfaceFeatureExtractDict, includedAngle, eMesh, surfaceFeatureConvert, ParaView Feature Edges, manual eMesh, normal glyph, flip normals, split geometry, rotating machinery]
see_also: [snappyhexmeshdict-reference.md, refinement-control.md, boundary-layers.md, sliding-meshes-ami-mrf.md]
source: Mixing-elbow, Ahmed-body, CSTR, boat-hull and Wolf-logo practical cases; OpenFOAM Meshing Lecture 1
---

# Geometry preparation

Good input geometry is the precondition for a good mesh. The factors that actually matter for the STL/OBJ are: **normals consistently oriented**, **no cracks or holes**, and **a single conformal body** wherever possible. Re-triangulating the surface (e.g. MeshMixer remesh to a uniform Delaunay triangulation) does **not** change the quality of the final `snappyHexMesh` output — do not spend effort on it expecting a quality gain. Place all geometry in `constant/triSurface`.

## STL vs OBJ — prefer OBJ when you need named regions

OBJ supports named face groups natively, which map directly to patch regions. In ASCII STL, regions are `solid <name>` / `endsolid <name>` blocks and must be edited by hand. In OBJ, groups are `g <groupname>` lines and those names become the region identifiers used in the `geometry` section of `snappyHexMeshDict`.

Assembling exported surfaces:
- **STL:** concatenate files with `cat` — straightforward.
- **OBJ:** the format carries vertex indices that must stay consistent, so concatenation is error-prone — use a tool such as MeshMixer to assign face groups and export a single OBJ.

OBJ face groups also let `surfaceCheck` detect intersections between regions automatically: each group boundary is a known intersection, giving more reliable feature/error detection than angle-based extraction on a monolithic STL.

## MeshMixer (Autodesk, free)

- **Face groups:** create automatically by an angle criterion (like `resolveFeatureAngle`), or by manual brush selection. Export as OBJ to preserve names; edit the `g <name>` lines in a text editor as needed.
- **Inspector (Edit → Inspector):** automated defect detection and repair. Blue markers = holes; click to auto-close. If auto-closure breaks surface tangency, manually select faces around the hole, then Erase & Fill with adjusted parameters (e.g. add bulge for tangency).
- Also re-triangulates, fixes non-manifold edges, and orients normals.

Blender offers similar capabilities but is harder to learn.

## Normals: check and fix

Normals must all point the same way (all out, or all in). Inconsistent normals do not always crash the mesher, but they break `refinementRegions` with `mode inside`/`outside`, because inside/outside is determined from normal orientation — volume refinement can silently land in the wrong place.

Check and fix with:
- **ParaView:** Filters → Alphabetical → **Normal Glyph** shows per-face arrows. To flip, use **Generate Surface Normals** with "Flip Normals", then File → Save Data as STL/OBJ.
- **`surfaceCheck <surface.stl>`** reports whether the surface is closed, normals are consistent, and whether there are disconnected regions.
- **`surfaceOrient`** orients all normals relative to a reference point:

```bash
surfaceOrient input_geo.stl '(1e10 1e10 1e10)' output_geo.stl
```

A reference far outside the geometry (e.g. `(1e10 1e10 1e10)`) is guaranteed to be outside any reasonable STL, so all normals are oriented to point away from it — i.e. outwards. A reference *inside* the STL orients them inwards.

### Related surface utilities

- **`surfaceTransformPoints`** — apply scaling, rotation, or translation directly to a surface file (the surface-level counterpart to `transformPoints` for meshes). Use it to scale a small geometry up before meshing, or to reposition an STL, without re-exporting from CAD.
- **`surfaceMeshTriangulate`** — extract and triangulate boundary patches from an existing OpenFOAM mesh into a surface file. Useful for turning an already-meshed boundary back into an STL (e.g. to drive refinement of a second mesh, or to inspect a patch as a surface).
- **`surfaceCheck`** — validate STL quality/topology (closed, consistent normals, disconnected regions) before meshing.

## Watertight surfaces and multi-body assembly

When a body is assembled from individually exported surfaces, the triangulations at shared edges may not match and the result is not watertight; `surfaceCheck` reports disconnected regions. The mesher usually still runs, but inside/outside detection for `refinementRegions` can be wrong. **A single solid exported from CAD is always preferred** — watertight, with matching triangulations at every edge.

Splitting a body into **multiple closed solids** is the robust alternative to assembling surfaces. Each closed solid passes `surfaceCheck` with no errors, normals are consistent, and `snappyHexMesh` treats the parts as one combined body — the result is essentially identical to a single-body STL. The critical requirement is that the parts match perfectly at their interfaces (no gaps, no interpenetration); a CAD cutting-plane split guarantees this automatically. This differs fundamentally from assembling open surfaces: closed solids have no gaps, no mismatched triangulation at shared edges, and no normal conflicts.

## Splitting geometry for rotating machinery

For rotating regions (MRF/sliding mesh), the shaft must be split at the interface so the inside portion moves with the rotor and the outside portion stays fixed. In CAD (e.g. Onshape Split with a reference plane at the interface), produce the inside and outside parts as separate STLs and read them as separate geometry entries. See `sliding-meshes-ami-mrf.md`.

## Fillets to ease boundary layers

Razor-sharp convex/concave angles are the worst case for layer growth. Adding fillets in CAD removes the sharp edge and replaces it with a smooth transition, eliminating the most collapse-prone region and reducing the need for high local refinement. Real physical objects rarely have perfectly sharp edges, so the simplification is usually acceptable. The improvement at filleted pipe junctions and concave corners is immediate and substantial. See `boundary-layers-at-sharp-edges.md`.

## Small geometries: write precision and scaling

For millimetre-scale geometries, `writePrecision 6` (the default in `controlDict`) can truncate when cell dimensions approach 10⁻⁶ m. Set high precision and binary format:

```openfoam
writeFormat     binary;
writePrecision  12;
```

Binary produces smaller files, less I/O, and preserves mesh information (especially small imperfections at refinement transitions) better than ASCII in practice. Alternatively — and often simplest — scale the geometry up before meshing to avoid precision problems entirely.

---

## Feature-edge extraction

Sharp edges (feature edges) must be extracted so the mesher can snap to and refine around them. Output is an `.eMesh` file in `constant/triSurface`, referenced later in `castellatedMeshControls::features` (application and `level` vs `levels` syntax are covered in `refinement-control.md`).

### surfaceFeatureExtract

Reads `system/surfaceFeatureExtractDict`; the `includedAngle` selects which edges are extracted (150° typical):

```openfoam
// system/surfaceFeatureExtractDict
surface.stl
{
    extractionMethod extractFromSurface;
    extractFromSurfaceCoeffs { includedAngle 150; }
    writeObj yes;
}
```

```bash
surfaceFeatureExtract
```

For smooth geometry (e.g. a sphere) there are no edges to resolve — do not run extraction and do not reference an `.eMesh`.

### When extraction misses edges (bluff bodies, complex hulls)

A single `includedAngle` on a monolithic STL can miss edges — e.g. rear-slant or base edges on a bluff body, or subtle curvature changes on a hull. Three remedies:

1. **Extract from individual surfaces.** Export each surface separately (e.g. a zero-thickness offset surface from CAD); `surfaceFeatureExtract` or ParaView's Feature Edges captures each surface's boundary edges cleanly, avoiding both missed edges and spurious noise. List each `.eMesh` independently in `features` (wildcards are not supported there).
2. **Write the `.eMesh` by hand.** The format is human-readable: point coordinates plus edge connectivity. For simple straight edges, read the two endpoints from CAD and enter them directly. Practical for the few edges extraction misses.
3. **ParaView Feature Edges at low angle.** A very low angle (2–3°) captures more edges but also the full triangulation wireframe; select the wanted edges interactively and extract them.

### ParaView edge extraction → eMesh

Apply **Feature Edges** with an angle, select edges with the selection tools, **Extract Selection**, **Extract Surface**, save as OBJ, then convert:

```bash
surfaceFeatureConvert constant/triSurface/ring.obj constant/triSurface/ring.eMesh
```

This allows selective extraction — e.g. only a junction ring for high refinement while the rest stays lower.

> ParaView versions newer than OpenFOAM supports may save VTK 5.1, which OpenFOAM cannot read (it supports up to VTK 4.2). Workaround: save as OBJ and convert with `surfaceFeatureConvert`.

## Surface imprinting (markings, logos, panel lines)

To capture surface markings without affecting overall mesh quality, export them as zero-thickness offset surfaces, add them as extra `geometry` entries, extract their feature edges, and use them for local refinement. Applicable to any local surface feature — panel lines, grilles, logos.
