"""pyvista off-screen rendering for CFD: fields, meshes, problem cells.

Design goal: a single function call produces a publication-clean PNG, so the
agent spends its effort on *what to show*, not on fighting VTK. Every renderer
here shares one look — white canvas, anti-aliased, a tidy labelled scalar bar,
an orientation triad — so a report's renders are visually consistent.

Requires pyvista + vtk. Rendering is off-screen (no display needed); on a
headless box VTK uses OSMesa/EGL automatically.
"""
from __future__ import annotations
import os
import contextlib
from . import style


@contextlib.contextmanager
def _silence_c_stdio():
    """Redirect C-level stdout/stderr to /dev/null. VTK occasionally dumps verbose
    framebuffer-status diagnostics straight to fd 1/2 during multi-renderer and
    orbit rendering on headless GL; this keeps the console clean. Output files are
    unaffected."""
    save1, save2 = os.dup(1), os.dup(2)
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 1); os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(save1, 1); os.dup2(save2, 2)
        os.close(devnull); os.close(save1); os.close(save2)

_INITED = False


def init_headless():
    """Force off-screen rendering and apply the cfdviz pyvista theme. Idempotent.

    Called automatically by the high-level helpers; call it yourself before any
    manual Plotter work so the first render doesn't try to open a window.
    """
    global _INITED
    import pyvista as pv
    pv.OFF_SCREEN = True
    if _INITED:
        return
    try:
        import vtk
        vtk.vtkObject.GlobalWarningDisplayOff()   # quiet non-fatal FBO/GL chatter
    except Exception:
        pass
    th = pv.themes.DocumentTheme()           # white background, sensible defaults
    th.background = "white"
    th.font.family = "arial"
    th.font.color = style.INK
    th.font.size = 16
    th.font.label_size = 14
    th.outline_color = style.SLATE
    th.edge_color = "#3a3a44"
    th.nan_color = "lightgrey"
    th.colorbar_orientation = "vertical"
    th.colorbar_vertical.width = 0.06
    th.colorbar_vertical.height = 0.55
    th.colorbar_vertical.position_x = 0.86
    th.colorbar_vertical.position_y = 0.22
    pv.global_theme.load_theme(th)
    _INITED = True


# ── Loading OpenFOAM ─────────────────────────────────────────────────────────
def open_foam(case, time="last", cell_to_point=True):
    """Read an OpenFOAM case. `case` is a .foam file or the case directory.

    Returns a dict:
        internal  -> UnstructuredGrid (the volume mesh + all fields)
        boundary  -> MultiBlock of patches (walls, airfoil, flange, …)
        patches   -> {patch_name: PolyData}
        reader    -> the OpenFOAMReader (inspect .time_values etc.)

    time: "last" (default), "first", a float, or an index int.
    cell_to_point: also expose cell fields as point data, which gives smooth
    slices/contours. OpenFOAM stores fields per cell, so this is usually wanted.
    """
    import pyvista as pv
    init_headless()
    if os.path.isdir(case):
        foams = [f for f in os.listdir(case) if f.endswith(".foam")]
        case = os.path.join(case, foams[0]) if foams else os.path.join(case, "case.foam")
    reader = pv.OpenFOAMReader(case)
    try:
        reader.enable_all_cell_arrays()
        reader.enable_all_point_arrays()
    except Exception:
        pass
    tv = list(reader.time_values)
    if tv:
        if time == "last":
            reader.set_active_time_value(tv[-1])
        elif time == "first":
            reader.set_active_time_value(tv[0])
        elif isinstance(time, int) and not isinstance(time, bool):
            reader.set_active_time_value(tv[time])
        else:
            reader.set_active_time_value(float(time))
    multi = reader.read()
    internal = multi["internalMesh"]
    if cell_to_point and internal.n_cells:
        try:
            internal = internal.cell_data_to_point_data(pass_cell_data=True)
        except Exception:
            pass
    patches = {}
    if "boundary" in multi.keys():
        bnd = multi["boundary"]
        for name in bnd.keys():
            blk = bnd[name]
            if blk is not None and getattr(blk, "n_points", 0):
                patches[name] = (blk.extract_surface(algorithm="dataset_surface")
                                 if hasattr(blk, "extract_surface") else blk)
    return {"internal": internal, "boundary": multi.get("boundary"),
            "patches": patches, "reader": reader, "multiblock": multi}


# ── The themed Plotter + scalar bar ──────────────────────────────────────────
def themed_plotter(size=(1600, 1100), title=None):
    """A white, anti-aliased off-screen Plotter with an orientation triad."""
    import pyvista as pv
    init_headless()
    p = pv.Plotter(off_screen=True, window_size=list(size))
    p.set_background("white")
    try:
        p.enable_anti_aliasing("ssaa")
    except Exception:
        pass
    if title:
        p.add_text(title, position="upper_left", font_size=14, color=style.INK)
    return p


def scalar_bar_args(field, vertical=True, fmt=None):
    """Consistent, readable scalar-bar styling. `field` sets the title+units."""
    title = style.label_for(field)
    if fmt is None:
        fmt = "%.3g"
    args = dict(
        title=title, n_labels=5, fmt=fmt, vertical=vertical,
        title_font_size=20, label_font_size=16, color=style.INK,
        font_family="arial", italic=False, bold=False, shadow=False,
        width=0.06 if vertical else 0.5, height=0.55 if vertical else 0.08,
        position_x=0.86 if vertical else 0.25,
        position_y=0.22 if vertical else 0.06,
    )
    return args


def _vector_magnitude(mesh, field):
    """If `field` is a vector, add a scalar magnitude array and return its name."""
    import numpy as np
    for assoc in (mesh.point_data, mesh.cell_data):
        if field in assoc:
            arr = assoc[field]
            if arr.ndim == 2 and arr.shape[1] == 3:
                name = field + "_mag"
                mesh[name] = np.linalg.norm(arr, axis=1)
                return name
            return field
    return field


def clim_for(mesh, scalar, field=None, percentile=(1, 99), diverging=None, center=0.0):
    """Robust color limits. Clips to [1,99] percentiles so a few outlier cells
    don't wash the map out (extremely common in CFD). For diverging fields the
    range is made symmetric about `center` so the neutral color is meaningful."""
    import numpy as np
    arr = None
    for assoc in (mesh.point_data, mesh.cell_data):
        if scalar in assoc:
            arr = np.asarray(assoc[scalar]).ravel()
            break
    if arr is None or arr.size == 0:
        return None
    arr = arr[np.isfinite(arr)]
    lo, hi = np.percentile(arr, percentile)
    if diverging is None and field is not None:
        diverging = style.is_diverging(field)
    if diverging:
        m = max(abs(lo - center), abs(hi - center))
        return [center - m, center + m]
    return [float(lo), float(hi)]


def save(plotter, path, scale=2):
    """Screenshot to `path` at `scale`× supersampling (crisp text & edges)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    plotter.screenshot(path, scale=scale)
    plotter.close()
    return path


# ── Framing: the #1 thing that separates a good CFD figure from a bad one ────
# A far-field domain is often 30–100× the body. Framing the whole domain makes
# the physics an invisible speck. These helpers frame to the BODY plus a margin
# so the near-field (the part that matters) fills the figure.
_FARFIELD_HINTS = ("inlet", "outlet", "far", "freestream", "top", "bottom",
                   "front", "back", "side", "symmetry", "atmosphere", "sky")


def is_body_patch(name):
    """True for a solid/wall patch (the thing the flow is about), False for
    far-field/boundary patches. Used to auto-frame and to pick surfaces."""
    return not any(h in name.lower() for h in _FARFIELD_HINTS)


def spans_domain(patch, mesh_bounds, frac=0.8):
    """True if a patch covers most of the domain in all 3 axes — i.e. it's an
    outer boundary (inlet/outlet/farfield/the domain box), regardless of its
    name. Catches a domain box misleadingly named 'walls', which a name-based
    heuristic can't. Used to exclude it from body framing/ghosting."""
    import numpy as np
    pb = np.array(patch.bounds, float).reshape(3, 2)
    mb = np.array(mesh_bounds, float).reshape(3, 2)
    msize = np.maximum(mb[:, 1] - mb[:, 0], 1e-12)
    psize = pb[:, 1] - pb[:, 0]
    return bool(np.all(psize / msize >= frac))


def real_body_patches(patches, mesh_bounds):
    """Patches that are the actual body: pass the name heuristic AND don't span
    the domain. Falls back to the name heuristic if geometry rules out everything."""
    body = {n: pd for n, pd in patches.items()
            if pd.n_points and is_body_patch(n)
            and not spans_domain(pd, mesh_bounds)}
    if not body:
        body = {n: pd for n, pd in patches.items()
                if pd.n_points and not spans_domain(pd, mesh_bounds)}
    return body


def body_bounds(patches, margin=6.0, mesh_bounds=None):
    """Union bounds of the body patches, expanded to `margin`× the body size so
    the near-field is visible. Returns a VTK bounds tuple or None.

    When `mesh_bounds` is given, patches that span the whole domain (an outer box
    even if named 'walls') are excluded geometrically — more robust than names."""
    import numpy as np
    if mesh_bounds is not None:
        bs = [p.bounds for p in real_body_patches(patches, mesh_bounds).values()]
    else:
        bs = [p.bounds for n, p in patches.items() if is_body_patch(n) and p.n_points]
    if not bs:
        return None
    bs = np.array(bs)
    lo = bs[:, [0, 2, 4]].min(axis=0)
    hi = bs[:, [1, 3, 5]].max(axis=0)
    c = (lo + hi) / 2
    half = np.maximum((hi - lo) / 2, 1e-9)
    half = half * margin
    return (c[0] - half[0], c[0] + half[0], c[1] - half[1], c[1] + half[1],
            c[2] - half[2], c[2] + half[2])


def expand_bounds(bounds, margin=2.5):
    """Expand a VTK bounds tuple to `margin`× its size about its center."""
    import numpy as np
    b = np.array(bounds, float).reshape(3, 2)
    c = b.mean(axis=1)
    half = np.maximum((b[:, 1] - b[:, 0]) / 2, 1e-9) * margin
    return (c[0] - half[0], c[0] + half[0], c[1] - half[1], c[1] + half[1],
            c[2] - half[2], c[2] + half[2])


def thin_axis(bounds, ratio=0.2):
    """Index (0=x,1=y,2=z) of an axis far thinner than the others (an extruded
    span), or None. Used to auto-pick a sensible view for 2-D-extruded cases."""
    import numpy as np
    b = np.array(bounds, float).reshape(3, 2)
    ext = b[:, 1] - b[:, 0]
    big = ext.max()
    for i, e in enumerate(ext):
        if big > 0 and e / big < ratio:
            return i
    return None


def frame_to(plotter, bounds, view="xy", zoom=1.0):
    """Point the camera at `bounds` (a VTK bounds tuple) in the given view.

    Uses focal-point + zoom-by-ratio rather than reset_camera(bounds=...), which
    silently fails to tighten in some VTK builds — the difference between a
    feature filling the frame and being an invisible speck."""
    import numpy as np
    set_view(plotter, view=view, zoom=1.0)   # fit all actors first
    if bounds is not None:
        b = np.array(bounds, float).reshape(3, 2)
        center = b.mean(axis=1)
        region = float(np.linalg.norm(b[:, 1] - b[:, 0]))
        full = np.array(plotter.bounds, float).reshape(3, 2)
        full_diag = float(np.linalg.norm(full[:, 1] - full[:, 0]))
        try:
            plotter.set_focus(tuple(center))
        except Exception:
            pass
        if region > 0 and full_diag > 0:
            plotter.camera.zoom(max(full_diag / region, 1.0) * 0.9)
    if zoom != 1.0:
        plotter.camera.zoom(zoom)


# ── Camera presets ───────────────────────────────────────────────────────────
def set_view(plotter, view="xy", zoom=1.0, bounds=None):
    """Common camera presets. `view`: xy/xz/yz (axis-aligned, good for slices &
    spanwise-extruded 2-D-like cases) or iso (3-D geometry). `bounds` (a mesh's
    .bounds) tightens the framing to a feature."""
    v = view.lower()
    if v == "xy":
        plotter.view_xy()
    elif v == "xz":
        plotter.view_xz()
    elif v == "yz":
        plotter.view_yz()
    else:
        plotter.view_isometric()
    if bounds is not None:
        plotter.reset_camera(bounds=bounds)
    if zoom != 1.0:
        plotter.camera.zoom(zoom)


# ── HIGH-LEVEL ONE-CALL RENDERERS ────────────────────────────────────────────
def field_slice(case_or_mesh, field, out, *, normal="z", origin=None,
                cmap=None, clim=None, view="xy", title=None, size=(1600, 1100),
                show_geometry=True, geometry_color="#1a1a1a", zoom=1.0,
                contour=False, n_contours=12, margin=4.0, focus=None):
    """Slice a volume and colour the cut plane by `field` — the workhorse for
    pressure/velocity fields on spanwise-extruded cases (airfoils, etc.).

    case_or_mesh: a .foam path/dir, a dict from open_foam, or an internal mesh.
    normal: slice plane normal ('z' is mid-span for 2-D-extruded geometries).
    show_geometry: overlay the solid boundary outline for context.
    contour: also draw iso-lines on the slice (great for pressure).
    margin: frame the camera to `margin`× the body size (NOT the whole far-field
            domain — that buries the physics). Pass a larger value to see more
            of the wake. `focus`=explicit bounds tuple overrides auto-framing;
            focus="domain" shows the entire slice.
    """
    import numpy as np
    if isinstance(case_or_mesh, str):
        data = open_foam(case_or_mesh)
        mesh, patches = data["internal"], data["patches"]
    elif isinstance(case_or_mesh, dict):
        mesh, patches = case_or_mesh["internal"], case_or_mesh.get("patches", {})
    else:
        mesh, patches = case_or_mesh, {}

    scalar = _vector_magnitude(mesh, field)
    if origin is None:
        origin = mesh.center
    sl = mesh.slice(normal=normal, origin=origin)
    cmap = cmap or style.cmap_for(field)
    clim = clim or clim_for(sl, scalar, field=field)

    p = themed_plotter(size=size, title=title)
    p.add_mesh(sl, scalars=scalar, cmap=cmap, clim=clim,
               scalar_bar_args=scalar_bar_args(field),
               nan_color="lightgrey", smooth_shading=False)
    if contour:
        try:
            cont = sl.contour(n_contours, scalars=scalar)
            p.add_mesh(cont, color="black", line_width=1.0, opacity=0.5)
        except Exception:
            pass
    if show_geometry and patches:
        for name, patch in patches.items():
            if any(k in name.lower() for k in ("inlet", "outlet", "far", "freestream",
                                               "top", "bottom", "front", "back", "side")):
                continue
            try:
                edge = patch.slice(normal=normal, origin=origin)
                if edge.n_points:
                    p.add_mesh(edge, color=geometry_color, line_width=3)
                else:
                    p.add_mesh(patch, color=geometry_color, opacity=0.9)
            except Exception:
                pass
    # Frame to the body, not the whole far-field domain.
    fb = None
    if focus == "domain":
        fb = None
    elif focus is not None:
        fb = focus
    elif patches:
        fb = body_bounds(patches, margin=margin, mesh_bounds=mesh.bounds)
    frame_to(p, fb, view=view, zoom=zoom)
    p.add_axes(color=style.INK)
    return save(p, out)


def surface_field(case_or_data, field, out, *, patch=None, cmap=None, clim=None,
                  view="auto", title=None, size=(1600, 1100), zoom=1.2,
                  show_edges=False):
    """Colour a boundary surface (a wall / the body) by a field — e.g. pressure
    or Cp on an airfoil, y+ or wall shear on walls. `patch` selects a patch by
    substring; default picks the first non-farfield wall patch.

    view="auto" (default) looks down the extruded span for a 2-D-extruded body
    (so you see the section, not the span face edge-on) and uses iso otherwise.
    NOTE: for a 2-D-extruded body, the *chordwise distribution* of a surface
    quantity (Cp, Cf) is usually clearer as a line chart — see
    charts.cp_distribution / render.wall_profile — than as a surface render."""
    if isinstance(case_or_data, str):
        data = open_foam(case_or_data)
    else:
        data = case_or_data
    patches = data["patches"]
    chosen = None
    for name, pd in patches.items():
        low = name.lower()
        if patch and patch.lower() in low:
            chosen = (name, pd); break
        if patch is None and not any(k in low for k in
                ("inlet", "outlet", "far", "freestream", "top", "bottom",
                 "front", "back", "side", "symmetry")):
            chosen = (name, pd); break
    if chosen is None and patches:
        chosen = next(iter(patches.items()))
    name, pd = chosen
    scalar = _vector_magnitude(pd, field)
    cmap = cmap or style.cmap_for(field)
    clim = clim or clim_for(pd, scalar, field=field)
    p = themed_plotter(size=size, title=title or f"{style.label_for(field)} — {name}")
    p.add_mesh(pd, scalars=scalar, cmap=cmap, clim=clim, show_edges=show_edges,
               edge_color="#3a3a44", line_width=0.3,
               scalar_bar_args=scalar_bar_args(field), smooth_shading=True)
    if view == "auto":
        # Look down the SPAN of a 2-D-extruded case — the axis where the whole
        # DOMAIN is thin (not the body's thinnest axis, which for an airfoil is
        # its thickness and would show only an edge-on sliver).
        internal = data.get("internal") if isinstance(data, dict) else None
        ti = thin_axis(internal.bounds) if internal is not None else thin_axis(pd.bounds)
        view = ["yz", "xz", "xy"][ti] if ti is not None else "iso"
    set_view(p, view=view, zoom=zoom)
    p.add_axes(color=style.INK)
    return save(p, out)


def wall_profile(case_or_data, field, *, patch=None, normal="z", origin=None,
                 chord_axis=0, split_axis=1):
    """Extract a surface quantity around a 2-D-extruded body section, ordered for
    a chordwise distribution plot (Cp, Cf, p). Slices the body patch at mid-span
    so the result is the section outline (avoiding the trap that surface nodes
    exist only on the z=±span planes), then splits into upper/lower surfaces.

    Returns ((x_u, v_u), (x_l, v_l)) where x is normalised to [0,1] along the
    chord. Feed straight into charts.cp_distribution (convert with charts.cp_from_p
    first if you want Cp). chord_axis/split_axis are coordinate indices (0=x,1=y,2=z).
    """
    import numpy as np
    data = open_foam(case_or_data) if isinstance(case_or_data, str) else case_or_data
    patches = data["patches"]
    pd = None
    for n, cand in patches.items():
        if (patch.lower() in n.lower()) if patch else is_body_patch(n):
            pd = cand; break
    if pd is None:
        raise ValueError("no body patch found for wall_profile")
    o = origin if origin is not None else pd.center
    sec = pd.slice(normal=normal, origin=o)
    if field not in sec.point_data and field in sec.cell_data:
        sec = sec.cell_data_to_point_data()
    pts = sec.points
    vals = np.asarray(sec.point_data[field]).ravel() if field in sec.point_data \
        else np.linalg.norm(sec.point_data[field], axis=1)
    x = pts[:, chord_axis]; s = pts[:, split_axis]
    xmin, xmax = x.min(), x.max()
    xn = (x - xmin) / (xmax - xmin + 1e-30)
    upper = s >= np.median(s)
    ou = np.argsort(xn[upper]); ol = np.argsort(xn[~upper])
    return ((xn[upper][ou], vals[upper][ou]), (xn[~upper][ol], vals[~upper][ol]))


def streamlines(case_or_data, out, *, vector="U", color_by="U", source_radius=None,
                source_center=None, n_points=600, normal="z", origin=None,
                tube_radius=None, cmap=None, clim=None, view="xy", title=None,
                size=(1600, 1100), zoom=1.0, show_geometry=True, margin=6.0,
                focus=None):
    """Seed streamlines through the volume, drawn as tubes coloured by speed.
    Reveals separation, wakes, recirculation.

    By default seeds are placed AROUND the body (not scattered across the whole
    far-field, which just yields parallel freestream lines) and the camera is
    framed to the near-field. Override source_center/source_radius to probe a
    specific region, or margin/focus to reframe."""
    if isinstance(case_or_data, str):
        data = open_foam(case_or_data)
    else:
        data = case_or_data
    import numpy as np
    import pyvista as pv
    mesh, patches = data["internal"], data.get("patches", {})
    bb = body_bounds(patches, margin=1.0, mesh_bounds=mesh.bounds) if patches else None
    b = bb or mesh.bounds
    if source_center is None:
        source_center = [(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2]
    # Seed a CROSS-STREAM line in the slice plane. Critically, ignore the
    # slice-normal axis (for a 2-D-extruded case that's the homogeneous span — if
    # we sized the seed by it the seeds spread through the whole span and you get
    # parallel freestream lines instead of flow wrapping the body).
    naxis = {"x": 0, "y": 1, "z": 2}.get(str(normal).lower(),
                                         2 if not hasattr(normal, "__len__") else 2)
    ext = [b[1] - b[0], b[3] - b[2], b[5] - b[4]]
    inplane = [i for i in range(3) if i != naxis]
    # streamwise = larger in-plane body extent (chord); cross-stream = the other
    stream_ax, cross_ax = (inplane if ext[inplane[0]] >= ext[inplane[1]]
                           else inplane[::-1])
    if source_radius is None:
        source_radius = 1.8 * max(ext[cross_ax], 0.15 * ext[stream_ax])
    pa = list(source_center); pb_ = list(source_center)
    pa[cross_ax] -= source_radius; pb_[cross_ax] += source_radius
    # place the rake slightly upstream of the body so lines develop over it
    pa[stream_ax] -= 0.5 * ext[stream_ax]; pb_[stream_ax] -= 0.5 * ext[stream_ax]
    seed = pv.Line(pa, pb_, resolution=max(n_points, 60))
    try:
        stream = mesh.streamlines_from_source(
            seed, vectors=vector, integration_direction="both", max_steps=8000)
    except Exception:
        stream = mesh.streamlines(
            vectors=vector, n_points=n_points, source_radius=source_radius,
            source_center=tuple(source_center), integration_direction="both",
            max_steps=8000)
    span = max(mesh.bounds[1] - mesh.bounds[0], mesh.bounds[3] - mesh.bounds[2])
    if tube_radius is None:
        tube_radius = 0.0015 * span
    tubes = stream.tube(radius=tube_radius)
    scalar = _vector_magnitude(tubes, color_by)
    cmap = cmap or style.cmap_for(color_by)
    p = themed_plotter(size=size, title=title)
    p.add_mesh(tubes, scalars=scalar, cmap=cmap, clim=clim,
               scalar_bar_args=scalar_bar_args(color_by))
    if show_geometry and patches:
        sorigin = origin or source_center
        for name, patch in patches.items():
            if not is_body_patch(name):
                continue
            drawn = False
            # For a 2-D-extruded body in an axis-aligned view, a filled slice
            # outline reads as a solid silhouette instead of an edge-on sliver.
            if view in ("xy", "xz", "yz"):
                try:
                    cut = patch.slice(normal=normal, origin=sorigin)
                    if cut.n_points:
                        p.add_mesh(cut, color="#1a1a1a", line_width=4)
                        drawn = True
                except Exception:
                    pass
            if not drawn:
                p.add_mesh(patch, color="#1a1a1a", opacity=0.9)
    fb = None if focus == "domain" else (focus if focus is not None
                                         else (body_bounds(patches, margin=margin,
                                               mesh_bounds=mesh.bounds)
                                               if patches else None))
    frame_to(p, fb, view=view, zoom=zoom)
    p.add_axes(color=style.INK)
    return save(p, out)


# ── MESH & GEOMETRY ──────────────────────────────────────────────────────────
def mesh_overview(case_or_data, out, *, view=None, title="Mesh", size=(1600, 1100),
                  zoom=1.0, surface_color="#cfd6dd", edge_color="#2b2b33",
                  slice_normal=None, slice_origin=None, style_="slice",
                  color_by=None, margin=4.0, focus=None, line_width=0.5):
    """Show the mesh structure.

    No `slice_normal`: the boundary surface with edges (far-field ghosted),
    framed to the body.

    `view` defaults sensibly: looking straight down the slice plane when a
    planar `slice_normal` is given (so the cut faces aren't seen edge-on), and
    isometric otherwise. Override explicitly to taste.

    With `slice_normal`: expose the interior. Two styles —
      style_="slice"  (default) a TRUE planar cut (cut faces). This is the right
                      choice for a flat, edge-on view: it shows grading and
                      refinement cleanly. Optionally `color_by` a field so the
                      refinement story and a quality story share one frame.
      style_="crinkle" whole cells on one side of the plane — a 3-D peek at cell
                      shapes, best viewed isometrically (a crinkle clip viewed
                      flat lets the nearest cell layer occlude everything).

    Framing defaults to the body × `margin` so far-field-heavy cases (the body is
    a speck in a big domain) stay readable. `focus="domain"` shows everything.
    """
    if isinstance(case_or_data, str):
        data = open_foam(case_or_data, cell_to_point=(color_by is not None))
    else:
        data = case_or_data
    mesh, patches = data["internal"], data.get("patches", {})
    if view is None:
        # look down a planar cut so faces aren't edge-on; iso for crinkle/surface
        view = ({"x": "yz", "y": "xz", "z": "xy"}.get(str(slice_normal).lower(), "iso")
                if (slice_normal is not None and style_ == "slice") else "iso")
    bb = body_bounds(patches, margin=margin, mesh_bounds=mesh.bounds) if patches else None
    p = themed_plotter(size=size, title=title)
    if slice_normal is not None:
        origin = slice_origin
        if origin is None:
            # centre the cut on the body, not the domain
            body_c = body_bounds(patches, margin=1.0, mesh_bounds=mesh.bounds) if patches else None
            origin = ((body_c[0] + body_c[1]) / 2, (body_c[2] + body_c[3]) / 2,
                      (body_c[4] + body_c[5]) / 2) if body_c else mesh.center
        # crop to the framed region first so the cut isn't a giant far-field slab
        src = mesh
        if bb is not None:
            try:
                src = mesh.clip_box(bb, invert=False)
            except Exception:
                src = mesh
        if style_ == "crinkle":
            cut = src.clip(normal=slice_normal, origin=origin, crinkle=True)
        else:
            cut = src.slice(normal=slice_normal, origin=origin)
        if color_by and (color_by in cut.cell_data or color_by in cut.point_data):
            p.add_mesh(cut, scalars=color_by, cmap=style.cmap_for(color_by),
                       clim=clim_for(cut, color_by), show_edges=True,
                       edge_color=edge_color, line_width=line_width,
                       scalar_bar_args=scalar_bar_args(color_by))
        else:
            p.add_mesh(cut, color=surface_color, show_edges=True,
                       edge_color=edge_color, line_width=line_width)
        # also draw the body outline on the cut plane for a spatial anchor
        for name, patch in patches.items():
            if is_body_patch(name):
                try:
                    edge = patch.slice(normal=slice_normal, origin=origin)
                    if edge.n_points:
                        p.add_mesh(edge, color="#111111", line_width=2.5)
                except Exception:
                    pass
    else:
        for name, patch in patches.items():
            p.add_mesh(patch, color=surface_color, show_edges=True,
                       edge_color=edge_color, line_width=0.4,
                       opacity=1.0 if is_body_patch(name) else 0.06)
    fb = None if focus == "domain" else (focus if focus is not None else bb)
    frame_to(p, fb, view=view, zoom=zoom)
    p.add_axes(color=style.INK)
    return save(p, out)


def _as_geom_data(case_or_data):
    """Normalise input to a {patches:{...}} dict for geometry rendering. Accepts a
    case path, an open_foam dict, or a raw mesh/STL from pyvista.read."""
    if isinstance(case_or_data, str):
        return open_foam(case_or_data, cell_to_point=False)
    if isinstance(case_or_data, dict):
        return case_or_data
    return {"patches": {"surface": case_or_data}}


def select_patches(data, which="body"):
    """Pick patches: "body" (default, non-farfield), "all", a name substring, or a
    list of names. Returns an ordered dict {name: PolyData}."""
    patches = data.get("patches", {})
    if isinstance(which, (list, tuple, set)):
        want = {w.lower() for w in which}
        sel = {n: p for n, p in patches.items()
               if p.n_points and any(w in n.lower() for w in want)}
    elif which == "all":
        sel = {n: p for n, p in patches.items() if p.n_points}
    elif which == "body" or which is None:
        sel = {n: p for n, p in patches.items() if p.n_points and is_body_patch(n)}
    else:  # substring
        sel = {n: p for n, p in patches.items()
               if p.n_points and which.lower() in n.lower()}
    if not sel and patches:
        sel = {n: p for n, p in patches.items() if p.n_points}
    return sel


def _union_bounds(meshes):
    import numpy as np
    bs = np.array([m.bounds for m in meshes])
    return (bs[:, 0].min(), bs[:, 1].max(), bs[:, 2].min(), bs[:, 3].max(),
            bs[:, 4].min(), bs[:, 5].max())


def _draw_geometry(p, sel, *, color_by_patch, color, show_edges, edge_color,
                   opacity=1.0):
    """Add geometry patches to a plotter, one colour each or a single colour.
    Returns legend entries [(name, color)]. The legend itself is composited
    afterwards by `_save_with_legend` (a clean matplotlib legend reads far better
    than pyvista's colored-text legend)."""
    entries = []
    for i, (n, pd) in enumerate(sel.items()):
        c = style.OKABE_ITO[i % len(style.OKABE_ITO)] if color_by_patch else color
        p.add_mesh(pd, color=c, show_edges=show_edges, edge_color=edge_color,
                   line_width=0.3, smooth_shading=True, opacity=opacity)
        entries.append((n, c))
    return entries


def _save_with_legend(plotter, out, entries, *, loc="upper right", scale=2,
                      title=None):
    """Screenshot the plotter and composite a clean matplotlib legend (colour
    swatches + dark text in a white box) over it. Far tidier than pyvista's
    native legend, which colours the label text itself."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    with _silence_c_stdio():
        img = plotter.screenshot(return_img=True, scale=scale)
    plotter.close()
    h, w = img.shape[:2]
    fig = plt.figure(figsize=(w / 200, h / 200), dpi=200)
    ax = fig.add_axes([0, 0, 1, 1]); ax.imshow(img); ax.set_axis_off()
    handles = [Patch(facecolor=c, edgecolor="none", label=n) for n, c in entries]
    leg = ax.legend(handles=handles, loc=loc, frameon=True, framealpha=0.96,
                    facecolor="white", edgecolor=style.HAIRLINE, fontsize=11,
                    labelcolor=style.INK, borderpad=0.7, handlelength=1.1,
                    labelspacing=0.5, title=title)
    if title and leg.get_title():
        leg.get_title().set_color(style.INK)
        leg.get_title().set_fontweight("bold")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    fig.savefig(out, dpi=200); plt.close(fig)
    return out


def geometry(case_or_data, out, *, patches="body", view="iso", title=None,
             size=(1600, 1100), zoom=1.0, color="#b9c2cc", color_by_patch=False,
             show_edges=True, edge_color="#2b2b33", margin=1.4, legend=True):
    """A clean surface-mesh / geometry figure (no scalar field needed).

    patches: "body" (default), "all", a name substring, or a list of names.
    color_by_patch: give each patch a distinct colour + a legend — ideal for
    showing boundary topology (inlet/outlet/walls/body, or each flange face).
    Otherwise a single neutral colour with the surface mesh edges. Accepts a case
    path, an open_foam dict, or a raw mesh/STL from pyvista.read."""
    data = _as_geom_data(case_or_data)
    sel = select_patches(data, patches)
    if not sel:
        raise ValueError("no patches to render")
    p = themed_plotter(size=size, title=title)
    entries = _draw_geometry(p, sel, color_by_patch=color_by_patch, color=color,
                             show_edges=show_edges, edge_color=edge_color)
    frame_to(p, expand_bounds(_union_bounds(list(sel.values())), margin),
             view=view, zoom=zoom)
    p.add_axes(color=style.INK)
    if color_by_patch and legend and len(entries) > 1:
        return _save_with_legend(p, out, entries)
    return save(p, out)


def multiview(case_or_data, out, *, patches="body", views=("iso", "xy", "xz", "yz"),
              color_by_patch=True, color="#b9c2cc", show_edges=False,
              edge_color="#2b2b33", size=(1700, 1400), title=None, margin=1.3,
              legend=True):
    """Montage of the geometry from several standard angles in one figure — the
    fast way to understand a shape and its boundary topology. `views` are any of
    iso/xy/xz/yz (front/top/side). Colour-by-patch is on by default so each
    boundary reads distinctly across all panels."""
    import pyvista as pv
    init_headless()
    data = _as_geom_data(case_or_data)
    sel = select_patches(data, patches)
    if not sel:
        raise ValueError("no patches to render")
    bounds = expand_bounds(_union_bounds(list(sel.values())), margin)
    n = len(views)
    rows = 1 if n <= 2 else 2
    cols = -(-n // rows)
    p = pv.Plotter(off_screen=True, window_size=list(size), shape=(rows, cols))
    p.set_background("white")
    try:
        p.enable_anti_aliasing("ssaa")
    except Exception:
        pass
    labels = {"iso": "isometric", "xy": "top (xy)", "xz": "front (xz)", "yz": "side (yz)"}
    entries = []
    for i, v in enumerate(views):
        p.subplot(i // cols, i % cols)
        entries = _draw_geometry(p, sel, color_by_patch=color_by_patch, color=color,
                                 show_edges=show_edges, edge_color=edge_color)
        frame_to(p, bounds, view=v, zoom=1.0)
        p.add_text(labels.get(v, v), position="upper_left", font_size=11, color=style.INK)
        p.add_axes(color=style.INK)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    if color_by_patch and legend and len(entries) > 1:
        return _save_with_legend(p, out, entries, loc="upper center")
    with _silence_c_stdio():
        p.screenshot(out, scale=2)
    p.close()
    return out


def orbit(case_or_data, out, *, patches="body", color_by_patch=False,
          color="#b9c2cc", show_edges=False, edge_color="#2b2b33", n_frames=72,
          size=(1100, 850), fps=10, margin=1.3, title=None, factor=2.2):
    """A turntable GIF orbiting the geometry — the most natural way to explore a
    3-D shape. Writes an animated GIF to `out` (use a .gif path).

    Rotation speed = fps / n_frames revolutions·sec⁻¹: the defaults (72 frames at
    10 fps) give a slow, smooth ~7 s turn. Lower fps or raise n_frames to slow it
    further."""
    import pyvista as pv
    init_headless()
    data = _as_geom_data(case_or_data)
    sel = select_patches(data, patches)
    if not sel:
        raise ValueError("no patches to render")
    p = pv.Plotter(off_screen=True, window_size=list(size))
    p.set_background("white")
    _draw_geometry(p, sel, color_by_patch=color_by_patch, color=color,
                   show_edges=show_edges, edge_color=edge_color)
    if title:
        p.add_text(title, position="upper_left", font_size=12, color=style.INK)
    p.add_axes(color=style.INK)
    p.camera.zoom(1.0)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with _silence_c_stdio():
        path = p.generate_orbital_path(n_points=n_frames, shift=0.0, factor=factor)
        p.open_gif(out, fps=fps)
        p.orbit_on_path(path, write_frames=True, step=0.0)
    p.close()
    return out


def problem_cells(case_or_data, field, out, *, threshold=None, invert=None,
                  view="iso", title=None, size=(1600, 1100), zoom=1.0,
                  context_opacity=0.15, highlight_cmap=None, percentile=95,
                  margin=1.6, markers="auto", marker_scale=0.012):
    """The mesh-debugging hero shot: extract the worst cells for a quality
    `field`, draw them in saturated colour inside a ghosted view of the BODY, and
    frame the camera tightly on them — so a reviewer instantly sees WHERE the bad
    cells cluster and how bad they are.

    Crucially this frames to the bad cells (× `margin`), NOT the whole far-field
    domain, and ghosts the body surface rather than the domain box — otherwise on
    any case where the domain dwarfs the body the bad cells are an invisible speck.

    markers: "auto" (default) overlays field-coloured spheres at bad-cell centres
    when the cells are few/tiny so single cells on a feature edge stay visible;
    True forces them, False disables. marker_scale is the sphere radius as a
    fraction of the framed region's diagonal.

    threshold: cutoff value. If None, uses the `percentile` of the field and the
    correct direction (skewness/non-ortho high = bad; determinant/volume low = bad).
    Returns (path, n_highlighted, threshold_used).
    """
    import numpy as np
    if isinstance(case_or_data, str):
        data = open_foam(case_or_data, cell_to_point=False)
    else:
        data = case_or_data
    mesh, patches = data["internal"], data.get("patches", {})
    arr = None
    for assoc in (mesh.cell_data, mesh.point_data):
        if field in assoc:
            arr = np.asarray(assoc[field]).ravel(); break
    if arr is None:
        raise ValueError(f"field {field!r} not found; have "
                         f"{list(mesh.cell_data.keys())}")
    lower_bad = field in style.LOWER_IS_WORSE
    if invert is None:
        invert = lower_bad
    if threshold is None:
        threshold = float(np.percentile(arr[np.isfinite(arr)],
                                        100 - percentile if lower_bad else percentile))
    bad = mesh.threshold(threshold, scalars=field, invert=invert)
    n_bad = bad.n_cells
    cmap = highlight_cmap or style.CMAP["quality_warn"]
    clim = clim_for(bad, field) if n_bad else None
    p = themed_plotter(size=size, title=title or
                       f"{style.label_for(field)} — worst {n_bad} cells (> {threshold:.3g})")

    # Ghost the BODY for context — but skip any patch far larger than the bad
    # cells (e.g. a domain box that happens to be named "walls"): ghosting it
    # would bury the cells and the patch-name heuristic can't always tell them
    # apart. This keeps the hero shot tight on the actual feature.
    def _diag(bnds):
        return float(np.linalg.norm([bnds[1] - bnds[0], bnds[3] - bnds[2],
                                     bnds[5] - bnds[4]]))
    bad_diag = _diag(bad.bounds) if n_bad else 0.0
    body = list(real_body_patches(patches, mesh.bounds).values())
    ghosted = False
    if body and bad_diag > 0:
        for pd in body:
            if _diag(pd.bounds) <= 8 * bad_diag:   # skip anything far bigger
                p.add_mesh(pd, color="#8a929c", opacity=context_opacity)
                ghosted = True
    if not ghosted and not n_bad:
        try:
            p.add_mesh(mesh.extract_surface(algorithm="dataset_surface"),
                       color="#8a929c", opacity=context_opacity * 0.4)
        except Exception:
            pass

    fb = None
    if n_bad:
        p.add_mesh(bad, scalars=field, cmap=cmap, clim=clim,
                   scalar_bar_args=scalar_bar_args(field), show_edges=True,
                   edge_color="#222222", line_width=0.4)
        fb = expand_bounds(bad.bounds, margin=margin)
        # marker overlay so sparse / tiny bad cells remain visible at body scale
        bb = bad.bounds
        diag = float(np.linalg.norm([bb[1] - bb[0], bb[3] - bb[2], bb[5] - bb[4]]))
        show_markers = (markers is True) or (markers == "auto" and n_bad <= 3000)
        if show_markers and diag > 0:
            import pyvista as pv
            centers = bad.cell_centers()
            centers[field] = (bad.cell_data[field] if field in bad.cell_data
                              else bad.point_data[field])
            centers.set_active_scalars(field)
            glyphs = centers.glyph(geom=pv.Sphere(radius=marker_scale * diag),
                                   scale=False, orient=False)
            p.add_mesh(glyphs, scalars=field, cmap=cmap, clim=clim,
                       show_scalar_bar=False)
    frame_to(p, fb, view=view, zoom=zoom)
    p.add_axes(color=style.INK)
    return save(p, out), n_bad, threshold
