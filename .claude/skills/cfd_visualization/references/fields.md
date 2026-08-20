# Flow fields

How to show what the flow is *doing* — pressure, velocity, turbulence,
temperature, vorticity — so a reviewer reads the physics, not just colors.

## Contents
- Choosing a representation
- Slices & contours
- Surface fields (loads on the body)
- Streamlines, glyphs, LIC
- Isosurfaces & volume
- Per-physics colormap & range cheatsheet
- Framing, lighting, annotation

## 2-D field maps (matplotlib) — the cleanest option for reports

For a 2-D or spanwise-extruded case (airfoil, cylinder, 2-D duct), a
matplotlib filled-contour **map** is usually the most readable, most
publication-ready way to present a field — more than a bare pyvista screenshot —
because it carries real coordinate axes (`x [m]`, `y [m]`), equal aspect, a white
body silhouette, and a clean labelled colorbar. Use `cfdviz.maps`:

- `maps.field_map(case, field, out, contour_lines=True)` — one panel.
- `maps.field_map_pair(case, field, out, suptitle=...)` — a **wide view + a
  near-body zoom**, sharing one colour scale. The wide view shows the **full
  domain** by default (`wide="full"`; pass a number for a body-size margin
  instead); the near view frames the body. Get them as one combined figure, or as
  two separate files with `separate=True` (writes `<out>_wide.png` and
  `<out>_near.png`) when you'd rather place them independently. This
  context+detail pairing is the clean way to show both the global field and the
  near-body detail.
- `maps.vector_field(case, out)` — a down-sampled quiver map (arrows on a regular
  grid, coloured by magnitude, over a faint magnitude tint). Always resampled to
  a legible spacing — never one arrow per cell.

Maps auto-frame to the body with a window aspect that gives a thin body room to
breathe (no letterbox strips). Pass `extent=((x0,x1),(y0,y1))` to fix the window,
`clim=` to fix the scale (essential when comparing two cases), `levels=` for
contour density. Use `render.*` (pyvista) instead when the geometry is genuinely
3-D, for streamlines/glyphs in 3-D, isosurfaces, or mesh cells.

## Choosing a representation

| Question | Representation | Helper |
| --- | --- | --- |
| Field in a plane, 2-D/extruded case, for a report | matplotlib map (axes, white body), single or wide+near pair | `maps.field_map`, `maps.field_map_pair` |
| Field structure in a plane (3-D-aware, quick) | slice colored by field, + iso-contours | `render.field_slice` |
| Loads / wall quantities on the body | surface render colored by field | `render.surface_field` |
| Where flow goes: separation, wake, recirculation, vortices | streamlines (tubes) colored by speed | `render.streamlines` |
| Direction + magnitude at points | glyphs (arrows) | see below |
| A coherent structure (shock, vortex core, shear layer) | isosurface of the relevant scalar | `mesh.contour` |
| Trends/distributions (Cp, residuals, y+) | a 2-D chart, NOT a render | `references/charts.md` |

Default to the simplest representation that answers the question. A mid-span
slice answers most 2-D-extruded questions; don't render a translucent 3-D volume
when a slice is clearer.

## Slices & contours

`render.field_slice(case_or_mesh, field, out, normal="z", contour=True, ...)`.

- For spanwise-extruded geometries (airfoils, 2-D-in-spirit cases) slice at
  mid-span with `normal="z"` and view `"xy"` — the default. For a duct/pipe use
  the cross-stream normal.
- **Contours on top of a colored field** read pressure/temperature structure far
  better than color alone — turn on `contour=True` (iso-lines drawn thin/black).
  Contour-only (line) plots suit black-and-white print.
- Vector fields (U) are auto-reduced to magnitude for coloring; to color by a
  component, add it first: `mesh["Ux"] = mesh["U"][:,0]` then pass `"Ux"`.
- Pressure is signed → diverging RdBu centered on freestream (0 for these cases).
  The helper detects this; if your freestream p ≠ 0, pass
  `clim=render.clim_for(sl, "p", diverging=True, center=p_inf)`.

## Surface fields (loads on the body)

`render.surface_field(case_or_data, field, out, patch=None, ...)` colors a wall
patch (auto-picks the body, or pass `patch="airfoil"`). Use for surface pressure,
Cp, wall shear / Cf, y+, heat flux. View `"iso"` for a 3-D body; `"xy"`/`"xz"`
for a 2-D-extruded one. For the *distribution along a chord/arc* prefer a line
chart (charts.md, `xy_plot` with `invert_y=True` for Cp).

## Recirculation & separation

The clearest 2-D way to find recirculation/separation:

- `maps.streamlines_2d(case, out)` — matplotlib streamlines on a slice, coloured
  and weighted by speed. A separated or recirculating region shows up
  unmistakably as **closed streamline loops**; line spacing shows where flow
  stalls. (Verified: on a synthetic vortex field it draws the closed cells; on
  attached flow it stays smooth.)
- `maps.recirculation(case, out)` — shades the region where the streamwise
  velocity is **negative** (flow running backward = the recirculation bubble) and
  draws the separation line (u·flow = 0), with streamlines on top. Returns the
  reversed-flow area fraction so you can quantify it. `flow_dir` defaults to the
  mean flow direction; set it explicitly for an angled free stream.
- For a 3-D separated wake, seed `render.streamlines` inside the wake
  (`source_center`/`source_radius`) so the integrator captures the reverse-flow
  core.

A reversed-flow region of ~0% on an attached case (e.g. an airfoil at 0°) is the
correct result, not a failure — there is simply nothing to recirculate.

## Streamlines, glyphs, LIC

- `render.streamlines(...)` seeds *around the body* and frames the near-field by
  default (seeding across the whole domain just yields parallel freestream
  lines). Tune `source_center`/`source_radius` to probe a wake or a specific
  region; raise `margin=` to follow the wake downstream. Color by speed by
  default — switch with `color_by="vorticity"` etc. after computing it.
- **Glyphs (arrows):** down-sample first or the plot turns to mush —
  `mesh.glyph(orient="U", scale="U", factor=..., tolerance=0.02)`; color by
  magnitude. Best for showing direction in recirculation zones, not whole fields.
- **Line Integral Convolution (LIC)** gives a dense, texture-like flow picture on
  a slice (`pyvista` surface LIC) — striking for boundary layers and wakes when a
  few streamlines look sparse. Use sparingly; it's slower.

## Isosurfaces & volume

- `iso = mesh.contour([v1, v2], scalars="field")` then `add_mesh(iso, ...)`.
  Common: Q-criterion or λ₂ isosurface for vortex cores (compute Q from the
  velocity gradient first), Mach=1 for shocks, a temperature isosurface for a
  plume. Color the isosurface by a *second* field (e.g. vortices colored by
  speed) to carry two variables at once.
- Volume rendering (`add_volume`) is occasionally worth it for a soft 3-D scalar
  cloud, but it's hard to read quantitatively — prefer slices + isosurfaces.

## Per-physics colormap & range cheatsheet

`style.cmap_for(field)` returns these automatically; override with `cmap=`.

| Field | Kind | Colormap | Range note |
| --- | --- | --- | --- |
| Velocity magnitude / speed | sequential | viridis | 0 → max; robust percentile clip |
| Velocity component (signed) | diverging | RdBu | center 0 |
| Pressure / Cp | diverging | RdBu | center on freestream (usually 0) |
| Vorticity / Q | diverging | RdBu | center 0 |
| k, ω, ε, νₜ (turbulence) | sequential | inferno | often log-like; consider log clim |
| Temperature | sequential | inferno | physical min→max |
| Passive scalar / concentration | sequential | viridis | 0→1 or physical |
| Mach | sequential | viridis (or diverging at M=1) | mark M=1 with a contour |

Turbulence quantities span orders of magnitude; if a linear map looks uniformly
dark, color by `log10` of the field (add a `log_field` array) and label the bar
accordingly.

## Framing, lighting, annotation

- **Frame the body** (SKILL.md rule). For comparisons (two meshes, two AoA),
  reuse the *same camera and the same `clim`* across renders so differences are
  real, not artifacts of autoscaling — pass an explicit `clim=` to each.
- Keep the orientation triad (`add_axes`, on by default) so the reader knows
  which way is up/downstream.
- Annotate the operating point (Re, Mach, AoA, inlet U) in the title or a corner.
  pyvista's text renderer is ASCII-only for some glyphs — write "alpha=4 deg"
  rather than "α=4°" in `add_text`, or composite the label in matplotlib. Charts
  (matplotlib/Plotly) handle full unicode/LaTeX fine.
- White background, anti-aliasing, and 2× supersampling are the toolkit defaults
  and give crisp, report-ready PNGs.
