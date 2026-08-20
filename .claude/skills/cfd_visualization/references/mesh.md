# Meshes & geometry

Mesh figures exist to answer "is this mesh good, and if not, *where* and *why*."
A picture of a whole mesh proves nothing; a picture that localises the bad cells
and shows their character is a diagnosis.

## Contents
- Quality fields and what "bad" means
- The problem-cell hero shot
- Quality distributions
- Mesh structure: surface, edges, clip/slice
- Boundary-layer / near-wall inspection
- Geometry & mesh-vs-CAD checks

## Quality fields and what "bad" means

OpenFOAM `checkMesh` and the writeable fields expose per-cell quality. Direction
matters — the toolkit knows it (`style.HIGHER_IS_WORSE`, `style.LOWER_IS_WORSE`):

| Field | Bad when | Typical limit |
| --- | --- | --- |
| `skewness` | high | > 4 (OpenFOAM), > 0.85 (Fluent-style 0–1) |
| `nonOrthoAngle` | high | > 70° serious; > 60–65° watch |
| `aspectRatio` / `cellAspectRatio` | high | > ~100 in bulk (BL cells legitimately higher) |
| `cellVolumeRatio` | high | abrupt jumps between neighbours |
| `faceWeight` | low | < ~0.05 |
| `cellDeterminant` | low | → 0 means near-degenerate |
| `minTetVolume` / `minPyrVolume` | low / negative | ≤ 0 is an invalid cell |

Always say what threshold you used and where it comes from (solver default vs
your judgement).

## The problem-cell hero shot

`render.problem_cells(case_or_data, field, out, threshold=None, percentile=95)`
is the workhorse: it extracts the worst cells for `field` (correct direction
auto-chosen) and draws them in saturated color inside a ghosted context mesh, so
the eye jumps straight to *where* the bad cells cluster and *how* bad they are.
Returns `(path, n_cells, threshold_used)` — report those numbers.

- Pass an explicit `threshold=` to use the solver's own limit (e.g. skewness 4)
  rather than a percentile, when you want "cells the solver would flag."
- Bad cells usually cluster at a geometric feature (a fillet, a sharp trailing
  edge, a snappyHexMesh feature edge). The localisation *is* the finding.
- It frames the camera tightly on the bad cells (not the far-field domain) and
  ghosts only the body, so the cluster fills the frame even when the domain is
  100× the body. Widen with `margin=`.
- Sparse single bad cells on a feature edge are easy to miss; `markers="auto"`
  overlays field-coloured spheres at bad-cell centres so they stay visible at
  body scale (force with `markers=True`, size with `marker_scale=`).

## Quality distributions

`charts.quality_histogram(values, out, field=, threshold=, higher_bad=)` turns a
wall of checkMesh numbers into one glance: the distribution, the acceptance
threshold marked, and the failing tail shaded red. Log-y by default because the
bad tail is usually a tiny fraction — which is exactly the point. Pull values
with `data["internal"].cell_data["skewness"]`.

## Mesh structure: surface, edges, clip/slice

`render.mesh_overview(case_or_data, out, slice_normal=None, ...)` — frames to the
body and crops the cut to the near-body region, so it works even when the domain
dwarfs the body:

- No slice → the boundary surface with edges drawn, far-field patches ghosted so
  the body and its surface mesh read clearly.
- `slice_normal="z"` → by default a **true planar slice** (`style_="slice"`, cut
  faces) — the right choice for a flat, edge-on view of grading, BL layers, and
  refinement transitions. `style_="crinkle"` keeps whole cells for a 3-D peek at
  cell shapes, but view it *isometrically* (a crinkle clip viewed flat lets the
  nearest cell layer occlude everything — a classic trap).
- `color_by="nonOrthoAngle"` (or any quality field) colours the cut so the
  refinement-grading story and the quality story share one frame. The body
  outline is drawn on the cut plane as a spatial anchor.
- Keep edge lines thin (≤0.5) so dense meshes don't turn into solid black.

## Geometry exploration

For understanding a shape and its boundary topology (no field needed):

- `render.geometry(case, out, color_by_patch=True)` — each patch in a distinct
  colour with a legend. The fastest way to see boundary conditions / topology
  (inlet, outlet, walls, body; or each face of a part). `patches=` selects what
  to show: `"body"` (default), `"all"`, a name substring, or a list of names.
  Without `color_by_patch` it's a clean single-colour surface-mesh figure.
  Accepts a case, an `open_foam` dict, or a raw mesh/STL from `pyvista.read`.
- `render.multiview(case, out)` — a montage from several standard angles
  (`views=("iso","xy","xz","yz")` = isometric / top / front / side) in one
  figure, colour-by-patch by default. The quickest way to read a 3-D shape.
- `render.orbit(case, out.gif)` — a turntable GIF orbiting the geometry, for
  interactive-feeling exploration or an HTML report (embed the GIF per the
  html-report conventions). Tune `n_frames`/`fps`.
- Zoom to the leading/trailing edge or a fillet (`render.geometry(..., patch=...,
  margin=...)`) to inspect surface mesh density at a feature.

## Boundary-layer / near-wall inspection

- Slice across the wall and zoom hard on the first cells; show edges. The story
  is: first-cell height, growth ratio, number of layers, and whether layers
  collapse or detach at curvature.
- Pair with a y+ plot/surface (`render.surface_field(..., "yPlus")` or
  `charts`): the mesh picture shows geometry, the y+ picture shows whether it's
  resolved for the chosen wall treatment.

## Geometry & mesh-vs-CAD checks

- Load CAD/STL with `pyvista.read("foo.stl")`; overlay the surface mesh on the
  STL (STL translucent, mesh edges on top) to expose faceting, gaps, or where the
  mesh fails to capture a fillet or sharp edge. Zoom to LE/TE/fillets — that's
  where snapping fails.
- Render the STL alone (smooth shading, soft light) for a clean geometry figure;
  add a scale reference or the bounding-box dimensions for context.
- For a defeaturing/clean-up check, color the STL by curvature or by feature
  angle to reveal sharp edges the mesher must respect.
