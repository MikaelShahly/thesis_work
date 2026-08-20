# pyvista recipes & gotchas

The `cfdviz.render` helpers cover the common path. This is for when you need to
go beyond them — custom scenes, comparisons, animation — without relearning the
gotchas each time. Everything here assumes off-screen rendering (no display).

## Contents
- Headless setup
- Reading data (OpenFOAM and others)
- Cell vs point data
- Cameras, multi-view, comparisons
- Scalar bars done right
- Lighting & background
- Animation
- Performance
- Common errors

## Headless setup

`render.init_headless()` sets `pyvista.OFF_SCREEN = True` and applies the white
DocumentTheme. Call it before any manual `Plotter`. On this box VTK renders via
the GPU/WSLg or OSMesa automatically — no Xvfb needed (and pyvista 0.48 has no
`start_xvfb`). Always create plotters with `off_screen=True` and end with
`plotter.screenshot(path, scale=2)` then `plotter.close()` (the toolkit's
`render.save` does this, including supersampling and directory creation).

## Reading data

- OpenFOAM: `render.open_foam(case, time="last")` returns
  `{internal, boundary, patches, reader, multiblock}`. `patches` is a dict of
  named boundary `PolyData` (walls, inlet, ...). It enables all cell+point arrays
  and converts cell→point data for smooth slicing.
- Other formats: `pyvista.read("file.vtu"/".vtk"/".cgns"/".stl"/".case")`.
  Multi-block (`.cgns`, Fluent `.cas`) returns a `MultiBlock`; index with
  `mb[0]` or `mb["zone"]`. Feed any resulting mesh straight into the `render.*`
  helpers (they accept a loaded mesh, not just a path).
- Time series: iterate `reader.time_values`, call
  `reader.set_active_time_value(t)`, re-`read()` each step.

## Cell vs point data

OpenFOAM stores fields per cell. Slicing/contouring look smoother on **point**
data; `open_foam(..., cell_to_point=True)` (default) provides both. Quality
fields are inherently per-cell — threshold and color them as cell data
(`mesh.cell_data["skewness"]`). Convert explicitly when needed:
`mesh = mesh.cell_data_to_point_data()` or `.point_data_to_cell_data()`.

## Cameras, multi-view, comparisons

- Presets: `render.set_view(p, "xy"|"xz"|"yz"|"iso")`. Frame to a region with
  `render.frame_to(p, bounds, view)` and `render.body_bounds(patches, margin)`.
- Save/restore an exact camera for repeatable comparisons:
  `cam = p.camera_position` then reuse it on the next plotter.
- **Side-by-side comparisons** (two meshes, two AoA, two times): use
  `pyvista.Plotter(shape=(1,2))`, `p.subplot(0,i)`, and `p.link_views()` so both
  panes share one camera. Use the *same* `clim` on both or the colors lie.
- Orthographic projection (`p.enable_parallel_projection()`) is often better for
  2-D-style slice views — no perspective distortion of a flat field.

## Scalar bars done right

`render.scalar_bar_args(field)` gives a titled, unit-labelled, tidy bar. Key
points if you build your own: set `title` to the quantity+units (not the array
name), `n_labels=5`, a sane `fmt` (`"%.3g"`), and place it clear of the data.
One bar per scalar; if two meshes share a field, share one bar (add the bar once,
reuse the mapper's `clim`). Add NaN color so masked cells read as grey, not as
the low end of the map.

## Lighting & background

White background (DocumentTheme) for reports. `p.enable_anti_aliasing("ssaa")`
(toolkit default) for clean edges. For 3-D geometry, `smooth_shading=True` plus
the default 3-point light reads volume well; for flat slices, lighting is
irrelevant — keep it simple. Avoid pure-black backgrounds for print figures.

## Animation

Convergence or transient sweeps:

```python
import imageio.v2 as imageio
frames = []
for t in reader.time_values:
    reader.set_active_time_value(t); mesh = reader.read()["internalMesh"]
    p = render.themed_plotter()
    p.add_mesh(mesh.slice("z"), scalars="U", cmap="viridis", clim=FIXED_CLIM)
    render.set_view(p, "xy")
    frames.append(p.screenshot(return_img=True)); p.close()
imageio.mimsave("out/anim.gif", frames, fps=10)   # or .mp4 via imageio-ffmpeg
```

Use a **fixed `clim`** across all frames or the colors flicker meaninglessly.
Off-screen plotters also support `p.open_gif(...)` / `p.write_frame()`.

## Performance

- 100k–1M cells render fine. For very large meshes, `mesh.decimate` (surfaces) or
  slice/clip *before* adding to the plotter; don't render the full volume to show
  a plane.
- Reading OpenFOAM is the slow step; load once and reuse the returned dict across
  many figures rather than re-reading per figure.

## Common errors

- **Color "#222" rejected** — VTK needs full 6-digit hex (`"#222222"`) or a CSS
  name.
- **`extract_surface` FutureWarning** — pass `algorithm="dataset_surface"`.
- **Unicode dropped in `add_text`** — VTK's text is ASCII-safe only for some
  glyphs; write "alpha", "deg" or composite labels in matplotlib. Charts handle
  unicode/LaTeX fine.
- **Blank/black render** — almost always a forgotten `off_screen=True` or a
  `clim` collapsed to a constant field (e.g. an unsolved t=0 case where U≡0).
- **Slice is empty** — the origin isn't inside the mesh; default to `mesh.center`.
