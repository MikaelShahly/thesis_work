---
name: visualization
description: >
  Produce fantastic, publication-quality scientific visualizations — with deep
  support for computational fluid dynamics (CFD). Use this WHENEVER creating any
  figure, plot, chart, field render, mesh view, or animation, and ALWAYS for CFD
  work: visualizing flow fields (pressure, velocity, vorticity, turbulence,
  temperature), slices/contours/streamlines/isosurfaces/glyphs, force and
  residual convergence, Cp/Cf/y+ distributions, and meshes/geometries (problem
  cells, quality fields, boundary layers, mesh-vs-CAD checks). Also use for
  general scientific plots (line/scatter/bar/histogram) headed for a report or
  paper. Triggers include OpenFOAM/SU2/Fluent/VTK cases, .foam files, checkMesh
  output, "visualize the simulation/results/mesh", "plot the residuals/forces",
  "show the pressure/velocity field". Tailors output to its destination — when
  the figures go into an HTML report, coordinate with the html-report skill so
  charts are interactive and styling matches. Do NOT use for UI mockups or
  diagrams that carry no data. Invoke without arguments.
---

# Scientific & CFD visualization

Make figures that a reviewer understands at a glance and that look like they
came from one careful hand. The bar is a peer-reviewed journal or a sharp
internal engineering report: no clutter, honest mapping of data to ink,
colorblind-safe, and visually striking because the *data* is presented well —
not because of decoration.

This skill specialises in **CFD** — simulation fields, convergence, and
mesh/geometry diagnostics — while remaining a solid general plotting guide.

## Start here: the `cfdviz` toolkit

Almost every CFD figure reinvents the same plumbing: headless rendering, reading
OpenFOAM, choosing a non-rainbow colormap, a legible scalar bar, framing the
camera on the body instead of the empty far-field, and matching the report's
fonts/colors. `assets/cfdviz/` does all of that, tested and consistent — so reach
for it first when it fits, rather than re-deriving the plumbing.

> **The toolkit is a starting point, not a fence.** It captures the *common*
> cases so you move fast and stay consistent; it is not the menu of allowed
> figures. Always make what best answers *this* situation. That routinely means
> changing parameters, composing helpers, calling pyvista/matplotlib/plotly
> directly, reaching for a library that isn't bundled (`uv add` it), or inventing
> a plot type the toolkit has no function for (a polar wake survey, a spectrogram,
> a phase portrait, a custom multi-panel, an animated sweep, a 3-D cutaway —
> whatever the data needs). The helpers also take already-loaded meshes/arrays,
> so you can pre-process freely and still get the consistent styling. What is
> binding is the **principles below** (clarity, honesty, colormap-by-meaning,
> framing, no overlap) — not any particular function. If a helper would force the
> data into the wrong representation, don't use it; build the right thing.

```python
import sys
sys.path.insert(0, "<this-skill>/assets")   # absolute path to the skill's assets
from cfdviz import render, charts, style, maps

# 2-D field MAPS (matplotlib: real x/y axes, white body, clean colorbar) — the
# cleanest, most publication-ready way to show a slice for a report. Prefer these
# for 2-D / spanwise-extruded cases over a bare 3-D screenshot.
maps.field_map_pair("case/foo.foam", "U", "out/U_field.png",      # wide + near, shared scale
                    suptitle="Velocity magnitude")
maps.field_map("case/foo.foam", "p", "out/p_field.png", contour_lines=True)  # single panel
maps.vector_field("case/foo.foam", "out/vectors.png")             # direction arrows, coloured by speed
maps.streamlines_2d("case/foo.foam", "out/streamlines.png")       # 2-D streamlines — see recirculation
maps.recirculation("case/foo.foam", "out/recirc.png")            # shade reversed-flow / separation zones

# 3-D / complex renders (pyvista, off-screen — no display needed)
render.field_slice("case/foo.foam", "p", "out/pressure.png", contour=True)  # 3-D-aware slice
render.surface_field("case/foo.foam", "p", "out/surface_p.png")     # Cp/p on the body
render.streamlines("case/foo.foam", "out/streamlines.png")          # 3-D streamline tubes
render.problem_cells("case/foo.foam", "skewness", "out/bad_cells.png")  # mesh QA hero shot
render.mesh_overview("case/foo.foam", "out/mesh.png", slice_normal="z",
                     color_by="nonOrthoAngle")                          # refinement + quality

# Geometry exploration (angles + per-patch colour)
render.geometry("case/foo.foam", "out/geometry.png", color_by_patch=True)   # patches in distinct colours + legend
render.multiview("case/foo.foam", "out/multiview.png")                       # iso/top/front/side montage
render.orbit("case/foo.foam", "out/orbit.gif")                               # turntable GIF

# 2-D charts (matplotlib static OR plotly interactive)
res = charts.parse_residuals("case/log.simpleFoam")
charts.residual_plot(res, "out/residuals.png")
co = charts.parse_force_coeffs("case/postProcessing/forceCoeffs/0/coefficient.dat")
charts.coeff_convergence(co, "out/forces.png")

# Cp distribution (the canonical airfoil deliverable)
(xu, vu), (xl, vl) = render.wall_profile("case/foo.foam", "p", patch="airfoil")
charts.cp_distribution((xu, charts.cp_from_p(vu, U_inf=20)),
                       (xl, charts.cp_from_p(vl, U_inf=20)), "out/cp.png")
```

Every function is documented in its docstring; skim the module before writing
custom code. If a case is non-OpenFOAM (SU2, CGNS, VTK, Fluent, plain CSV/STL),
load it with `pyvista.read(...)` / `numpy` and feed the mesh objects to the same
`render.*` helpers — they take a loaded mesh, not just a path. Install missing
packages into the project venv (`uv add <pkg>`); the venv already has pyvista,
vtk, matplotlib, scipy, plotly, imageio, meshio.

## Workflow

1. **Name the question the figure must answer.** "Did it converge?" "Where does
   the flow separate?" "Why is the mesh bad and where?" The question picks the
   representation — not habit, and not whichever helper exists. If the best answer
   is a figure the toolkit doesn't cover, make that figure.
2. **Pick the representation** that answers it; the references (below) survey the
   common families and their trade-offs to inform the choice.
3. **Produce it** — with `cfdviz` where it fits (overriding what the question
   needs), composing/extending it, or writing bespoke code when that's better.
4. **Run the pre-output checklist** before returning anything.

## Reference map — read the one you need

| If you are visualizing… | Read |
| --- | --- |
| Flow fields: 2-D maps (matplotlib), slices, contours, streamlines, glyphs, isosurfaces, vorticity; per-physics colormap & framing choices | `references/fields.md` |
| Meshes & geometry: problem cells, quality fields, clipping, boundary layers, mesh-vs-CAD, STL | `references/mesh.md` |
| 2-D charts: residuals, force/moment convergence, Cp/Cf, y+, profiles, quality histograms | `references/charts.md` |
| Output going into an HTML report (interactive charts, embedding, matching the design system) | `references/html.md` |
| pyvista mechanics: cameras, lighting, scalar bars, animation, multi-view, gotchas | `references/pyvista-recipes.md` |

## Core principles

1. **Clarity above all** — one idea per figure; nothing competes for attention.
   This is the bar the user cares about most: figures must be as clean and
   readable as possible.
2. **Accuracy** — the mapping from data to ink is honest. No truncated axes that
   exaggerate, no colormap that invents structure, no diverging map left
   off-center so the neutral value lies.
3. **Accessibility** — readable by someone with color vision deficiency.
4. **Professionalism** — clean, consistent, confident.

### Readability is non-negotiable: no overlap, room to breathe

The fastest way a figure looks amateur is crowding. Enforce:

- **Nothing overlaps** — not labels, ticks, legends, annotations, arrows, or
  data. If a legend sits on the data, move it out (or to empty space); if tick
  labels collide, thin them or rotate; if arrows form a mat, down-sample. The
  toolkit uses tight/constrained layout and the seaborn underlay to help, but
  check every figure with your eyes.
- **Context + detail beats cramming.** When one view can't show both the global
  picture and the part that matters, use a wide view (the full domain) plus a
  near-body zoom. `maps.field_map_pair` does this — as one figure, or as two
  separate files (`separate=True`) when you'd rather place them independently.
- **Generous whitespace and equal aspect** for fields, so geometry isn't
  distorted and the eye has room. Give the subject the frame; trim dead space
  around it but don't pack the margins.
- **Annotate the value, don't make the reader hunt** — put the converged number
  on the line, the percentage on the bar/wedge. For a breakdown, a bar
  (`charts.drag_breakdown`) usually makes magnitudes easiest to compare, but a
  pie is fine when you just need to convey a couple of proportions.

## The CFD-specific rules that matter most

These are where CFD figures usually go wrong. The toolkit applies them by
default; if you render by hand, apply them yourself.

### Colormap by physical meaning, never rainbow

Jet/rainbow fabricates banding and hides gradients — never use it. Pick by what
the field *means* (`style.cmap_for(field)` does this automatically):

- **Sequential, perceptually uniform** for magnitudes with a natural floor:
  velocity/speed → viridis; turbulence (k, ω, ε, νₜ) and temperature → inferno;
  generic scalar → viridis; wall distance → cividis.
- **Diverging, centered on the neutral value** for signed fields: pressure / Cp
  → RdBu (centered on freestream, usually 0); vorticity → RdBu centered on 0. A
  diverging map is a *lie* if its midpoint isn't the neutral value — use
  `render.clim_for(..., diverging=True, center=0)`.
- **Mesh quality** → cividis, with the failing cells highlighted separately (see
  mesh.md), so "where are the bad cells" is answered instantly.

### Frame the body, not the far-field

External-aero domains are often 30–100× the body. Showing the whole domain makes
the airfoil/car/building an invisible speck and the physics vanishes. **Frame the
near-field** — the `render.*` helpers auto-frame to the body patches with a
margin; widen `margin=` to show more wake, or pass `focus="domain"` only when the
far-field genuinely is the subject.

### Scalar bars are labelled, with units, and robustly scaled

Every field render carries a scalar bar titled with the quantity and its units
(`style.label_for`), not a bare variable name. Color limits use 1–99th
percentiles by default so a handful of outlier cells don't wash the whole map to
one color (`render.clim_for`). State the clipping if it matters.

### Show convergence honestly

Residuals on a log y-axis with the target marked. Force/moment coefficients with
the converged (windowed-mean) value annotated, so "is it converged" is visible,
not asserted.

## Output format

- **3-D / field renders** → high-resolution PNG (the toolkit supersamples 2×).
  Render at generous `size=` and let it downscale; crisp edges and text matter.
- **2-D charts** → vector (SVG/PDF) for print/LaTeX; PNG at ≥200 DPI otherwise;
  interactive Plotly when the destination is HTML (see html.md).
- Never JPEG for plots or renders (artifacts on edges and text).
- Match the destination: SVG + interactive for HTML, PDF for LaTeX, high-DPI PNG
  for raster/slides. When the destination is an HTML report, the `html-report`
  skill governs embedding — coordinate via `references/html.md`.

## Pre-output checklist

Before returning any figure, confirm:

- [ ] The figure answers its one question at a glance; no clutter or overlap.
- [ ] Sized so all detail is legible; the subject fills the frame (body framed,
      not the empty far-field).
- [ ] Colormap chosen by meaning; no rainbow/jet; diverging maps centered on the
      neutral value.
- [ ] Color limits robust (not dominated by outliers); clipping noted if relevant.
- [ ] Scalar bar / legend present, titled, with units; doesn't obscure data.
- [ ] Axes labelled with units; log scale where the data spans decades.
- [ ] One consistent font; styling matches the destination (HTML/LaTeX/slides).
- [ ] Colorblind-safe and information-bearing color.
- [ ] Uncertainty / convergence shown where relevant.
- [ ] Correct format (vector or high-DPI PNG/TIFF; never JPEG).
