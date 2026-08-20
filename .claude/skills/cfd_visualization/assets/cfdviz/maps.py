"""Matplotlib-rendered field maps for 2-D slices.

For a planar slice of a field, a matplotlib filled-contour map with real
coordinate axes (x [m], y [m]), equal aspect, a labelled colorbar, and a clean
white body silhouette reads as a *publication figure* — more so than a bare
pyvista screenshot. It also composes naturally into a context+detail pair (a
wide view beside a near-body zoom), which is the clearest way to show both the
global field and the part that matters without cramming or overlap.

Use this for 2-D / spanwise-extruded cases (airfoils, cylinders, 2-D ducts).
For genuinely 3-D geometry, complex surfaces, streamlines, or mesh cells, use
`render.*` (pyvista) instead.

Requires pyvista (to slice) + matplotlib. Honours the cfdviz style/colormaps.
"""
from __future__ import annotations
import os
import numpy as np
from . import style, render

_AXES = {"x": 0, "y": 1, "z": 2}


def _window(bb, ip, aspect=0.55):
    """Plotting window from body bounds, but with the cross-stream (y) half-extent
    grown to at least `aspect`× the streamwise (x) half-extent. A thin body (an
    airfoil) otherwise yields an unreadable letterbox strip under equal aspect;
    this gives the field room to breathe, like the reference figure."""
    x0, x1 = bb[2 * ip[0]], bb[2 * ip[0] + 1]
    y0, y1 = bb[2 * ip[1]], bb[2 * ip[1] + 1]
    xc, yc = (x0 + x1) / 2, (y0 + y1) / 2
    xh = (x1 - x0) / 2
    yh = max((y1 - y0) / 2, aspect * xh)
    return ((xc - xh, xc + xh), (yc - yh, yc + yh))


def _slice_triangulation(mesh, field, normal, origin, extent=None, patches=None):
    """Slice `mesh`, return (X, Y, Triangulation, values, in-plane axis indices).

    Triangles that bridge the body hole are masked two ways, robust for both a
    near-field clip and a full-domain view: by the body's outline polygon (so the
    body is removed even when far-field cells are huge), and by a generous
    edge-length cutoff tied to the *window* size (so ragged clip boundaries are
    trimmed without punching holes in legitimately large far-field cells)."""
    from matplotlib.tri import Triangulation
    naxis = _AXES.get(str(normal).lower(), 2)
    ip = [i for i in range(3) if i != naxis]
    o = origin if origin is not None else mesh.center
    sl = mesh.slice(normal=normal, origin=o)
    if extent is not None:
        (x0, x1), (y0, y1) = extent
        b = list(mesh.bounds)
        b[2 * ip[0]], b[2 * ip[0] + 1] = x0, x1
        b[2 * ip[1]], b[2 * ip[1] + 1] = y0, y1
        try:
            sl = sl.clip_box(b, invert=False)
        except Exception:
            pass
    if field not in sl.point_data:
        sl = sl.cell_data_to_point_data()
    tri = sl.triangulate()
    cd = tri.cells_dict
    faces = cd.get(5)  # VTK_TRIANGLE
    if faces is None or len(faces) == 0:
        poly = tri.extract_surface(algorithm="dataset_surface")
        faces = poly.faces.reshape(-1, 4)[:, 1:]
        tri = poly
    pts = tri.points
    X, Y = pts[:, ip[0]], pts[:, ip[1]]
    vals = np.asarray(tri.point_data[field]).ravel()
    if vals.ndim > 1 or (field in tri.point_data and tri.point_data[field].ndim == 2):
        vals = np.linalg.norm(tri.point_data[field], axis=1)
    triang = Triangulation(X, Y, faces)

    xt, yt = X[faces], Y[faces]
    e = np.hypot(np.diff(xt[:, [0, 1, 2, 0]], axis=1), np.diff(yt[:, [0, 1, 2, 0]], axis=1))
    maxedge = e.max(axis=1)
    wdiag = (np.hypot(extent[0][1] - extent[0][0], extent[1][1] - extent[1][0])
             if extent is not None else np.hypot(X.max() - X.min(), Y.max() - Y.min()))
    mask = maxedge > 0.08 * wdiag
    # body-polygon mask: remove triangles whose centroid is inside the body
    if patches:
        segs = _body_segments(patches, normal, o, ip)
        if segs:
            try:
                from scipy.spatial import ConvexHull
                from matplotlib.path import Path
                bpts = np.array([p for s in segs for p in s])
                hull = ConvexHull(bpts)
                poly = Path(bpts[hull.vertices])
                cx = X[faces].mean(axis=1); cy = Y[faces].mean(axis=1)
                mask |= poly.contains_points(np.column_stack([cx, cy]))
            except Exception:
                pass
    triang.set_mask(mask)
    return X, Y, triang, vals, ip


def _body_segments(patches, normal, origin, ip):
    """Line segments of the body section outline, for a crisp black silhouette."""
    segs = []
    for n, pd in patches.items():
        if not render.is_body_patch(n):
            continue
        try:
            cut = pd.slice(normal=normal, origin=origin)
        except Exception:
            continue
        if not cut.n_points or cut.n_cells == 0:
            continue
        lines = cut.lines
        if lines is None or len(lines) == 0:
            continue
        i = 0
        P = cut.points
        while i < len(lines):
            k = lines[i]
            idx = lines[i + 1:i + 1 + k]
            for a, b in zip(idx[:-1], idx[1:]):
                segs.append([(P[a, ip[0]], P[a, ip[1]]), (P[b, ip[0]], P[b, ip[1]])])
            i += k + 1
    return segs


def _body_hull(patches, normal, o, ip):
    """Convex-hull Path of the body section outline (for masking/filling)."""
    segs = _body_segments(patches, normal, o, ip)
    if not segs:
        return None, None
    try:
        from scipy.spatial import ConvexHull
        from matplotlib.path import Path
        bpts = np.array([p for s in segs for p in s])
        hull = ConvexHull(bpts)
        return Path(bpts[hull.vertices]), segs
    except Exception:
        return None, segs


def _add_body(ax, patches, normal, o, ip, fill=True):
    """Draw the body section: white fill (to hide streamlines crossing it) + a
    crisp black outline."""
    path, segs = _body_hull(patches, normal, o, ip)
    from matplotlib.collections import LineCollection
    if fill and path is not None:
        from matplotlib.patches import PathPatch
        ax.add_patch(PathPatch(path, facecolor="white", edgecolor="none", zorder=4))
    if segs:
        ax.add_collection(LineCollection(segs, colors="#111111", linewidths=1.4, zorder=5))


def _grid_vectors(mesh, vector, normal, o, extent, nx, patches, aspect=0.55):
    """Resample a slice's vector field onto a regular grid for streamplot/quiver.
    Returns (gx, gy, GX, GY, GU, GV, GM, ip)."""
    from scipy.interpolate import griddata
    naxis = _AXES.get(str(normal).lower(), 2)
    ip = [i for i in range(3) if i != naxis]
    sl = mesh.slice(normal=normal, origin=o)
    if vector not in sl.point_data:
        sl = sl.cell_data_to_point_data()
    P = sl.points; V = np.asarray(sl.point_data[vector])
    X, Y = P[:, ip[0]], P[:, ip[1]]
    if extent is None:
        extent = ((X.min(), X.max()), (Y.min(), Y.max()))
    ny = max(int(nx * (extent[1][1] - extent[1][0]) / (extent[0][1] - extent[0][0])), 8)
    gx = np.linspace(*extent[0], nx); gy = np.linspace(*extent[1], ny)
    GX, GY = np.meshgrid(gx, gy)
    GU = griddata((X, Y), V[:, ip[0]], (GX, GY), method="linear")
    GV = griddata((X, Y), V[:, ip[1]], (GX, GY), method="linear")
    GM = np.hypot(GU, GV)
    return gx, gy, GX, GY, GU, GV, GM, ip, extent


def streamlines_2d(case_or_data, out, *, vector="U", normal="z", origin=None,
                   extent=None, margin=0.6, aspect=0.55, nx=200, density=1.4,
                   cmap=None, clim=None, title=None, figsize=(10, 6),
                   linewidth=(0.4, 2.2)):
    """2-D streamlines (matplotlib streamplot) on a slice, coloured and weighted
    by speed. This is the clearest 2-D way to SEE recirculation and separation:
    a separated/recirculating region shows up as closed streamline loops, and the
    line spacing reveals where flow stalls. Complements the 3-D render.streamlines.

    Streamlines are drawn over the whole window then the body is over-painted, so
    none appear to cross it. Returns the path."""
    import matplotlib.pyplot as plt
    style.use_mpl_style(grid="none")
    if isinstance(case_or_data, str):
        data = render.open_foam(case_or_data); mesh, patches = data["internal"], data["patches"]
    elif isinstance(case_or_data, dict):
        mesh, patches = case_or_data["internal"], case_or_data.get("patches", {})
    else:
        mesh, patches = case_or_data, {}
    naxis = _AXES.get(str(normal).lower(), 2)
    ip = [i for i in range(3) if i != naxis]
    o = origin if origin is not None else mesh.center
    if extent is None and patches:
        bb = render.body_bounds(patches, margin=1 + margin, mesh_bounds=mesh.bounds)
        extent = _window(bb, ip, aspect) if bb is not None else None
    gx, gy, GX, GY, GU, GV, GM, ip, extent = _grid_vectors(mesh, vector, normal, o, extent, nx, patches, aspect)
    cmap = cmap or style.cmap_for(vector)
    if clim is None:
        clim = [float(np.nanmin(GM)), float(np.nanmax(GM))]
    lw = linewidth[0] + (linewidth[1] - linewidth[0]) * (GM - clim[0]) / (clim[1] - clim[0] + 1e-30)
    fig, ax = plt.subplots(figsize=figsize)
    strm = ax.streamplot(gx, gy, GU, GV, color=GM, cmap=cmap, density=density,
                         linewidth=np.clip(lw, *linewidth), arrowsize=0.9,
                         norm=plt.Normalize(*clim))
    _add_body(ax, patches, normal, o, ip, fill=True)
    cb = fig.colorbar(strm.lines, ax=ax, fraction=0.046, pad=0.02)
    cb.set_label(style.label_for(vector)); cb.outline.set_visible(False)
    an = ["x", "y", "z"]
    ax.set_xlabel(f"{an[ip[0]]} [m]"); ax.set_ylabel(f"{an[ip[1]]} [m]")
    ax.set_aspect("equal"); ax.set_xlim(*extent[0]); ax.set_ylim(*extent[1])
    if title:
        ax.set_title(title)
    fig.savefig(out, dpi=200, bbox_inches="tight"); plt.close(fig)
    return out


def recirculation(case_or_data, out, *, vector="U", normal="z", origin=None,
                  flow_dir=None, extent=None, margin=0.6, aspect=0.55, nx=240,
                  title=None, figsize=(10, 6), streamlines=True):
    """Highlight recirculation / separation: shade the region where the flow runs
    BACKWARD (streamwise velocity < 0) and draw the separation line (u·flow = 0),
    over a faint speed map, optionally with streamlines on top. The reversed-flow
    region is exactly the recirculation bubble.

    flow_dir: the free-stream direction (in-plane). Default: inferred from the
    mean velocity on the slice. Returns (path, reversed_area_fraction)."""
    import matplotlib.pyplot as plt
    style.use_mpl_style(grid="none")
    if isinstance(case_or_data, str):
        data = render.open_foam(case_or_data); mesh, patches = data["internal"], data["patches"]
    elif isinstance(case_or_data, dict):
        mesh, patches = case_or_data["internal"], case_or_data.get("patches", {})
    else:
        mesh, patches = case_or_data, {}
    naxis = _AXES.get(str(normal).lower(), 2)
    ip = [i for i in range(3) if i != naxis]
    o = origin if origin is not None else mesh.center
    if extent is None and patches:
        bb = render.body_bounds(patches, margin=1 + margin, mesh_bounds=mesh.bounds)
        extent = _window(bb, ip, aspect) if bb is not None else None
    gx, gy, GX, GY, GU, GV, GM, ip, extent = _grid_vectors(mesh, vector, normal, o, extent, nx, patches, aspect)
    if flow_dir is None:
        mv = np.array([np.nanmean(GU), np.nanmean(GV)])
        flow_dir = mv / (np.linalg.norm(mv) + 1e-30)
    else:
        flow_dir = np.array(flow_dir[:2], float); flow_dir /= np.linalg.norm(flow_dir) + 1e-30
    S = GU * flow_dir[0] + GV * flow_dir[1]            # streamwise component
    fig, ax = plt.subplots(figsize=figsize)
    ax.pcolormesh(GX, GY, GM, cmap=style.cmap_for(vector), shading="auto", alpha=0.25)
    rev = (S < 0).astype(float)
    ax.contourf(GX, GY, rev, levels=[0.5, 1.5], colors=[style.BAD], alpha=0.45)
    ax.contour(GX, GY, S, levels=[0.0], colors=[style.BAD], linewidths=1.4)
    if streamlines:
        ax.streamplot(gx, gy, GU, GV, color="#444444", density=1.3, linewidth=0.6,
                      arrowsize=0.8)
    _add_body(ax, patches, normal, o, ip, fill=True)
    frac = float(np.nansum(rev) / np.isfinite(S).sum())
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(facecolor=style.BAD, alpha=0.45,
              label=f"reversed flow ({100*frac:.1f}% of window)")],
              loc="upper right", frameon=True)
    an = ["x", "y", "z"]
    ax.set_xlabel(f"{an[ip[0]]} [m]"); ax.set_ylabel(f"{an[ip[1]]} [m]")
    ax.set_aspect("equal"); ax.set_xlim(*extent[0]); ax.set_ylim(*extent[1])
    ax.set_title(title or "Recirculation (reversed streamwise flow)")
    fig.savefig(out, dpi=200, bbox_inches="tight"); plt.close(fig)
    return out, frac


def field_map(case_or_data, field, out=None, *, normal="z", origin=None,
              extent=None, cmap=None, clim=None, levels=24, contour_lines=False,
              n_contour_lines=10, title=None, figsize=(9.5, 6.0), ax=None,
              add_cbar=True, body_color="white", margin=0.6, aspect=0.55):
    """Filled-contour map of a field on a planar slice, with coordinate axes.

    case_or_data: a .foam path/dir, an open_foam dict, or an internal mesh.
    extent: ((x0,x1),(y0,y1)) plotting window in metres, or a preset:
            "near"/None → the body plus `margin`× its size (the near-field);
            "full"      → the whole mesh/domain (use for a wide overview).
    contour_lines: overlay thin iso-lines (great for pressure).
    Pass `ax` (and add_cbar=False) to draw into an existing axes — used by
    field_map_pair. Returns (fig, ax). Writes a PNG if `out` is given.
    """
    import matplotlib.pyplot as plt
    style.use_mpl_style(grid="none")            # a field map wants no gridlines
    if isinstance(case_or_data, str):
        data = render.open_foam(case_or_data)
        mesh, patches = data["internal"], data["patches"]
    elif isinstance(case_or_data, dict):
        mesh, patches = case_or_data["internal"], case_or_data.get("patches", {})
    else:
        mesh, patches = case_or_data, {}

    naxis = _AXES.get(str(normal).lower(), 2)
    ip = [i for i in range(3) if i != naxis]
    o = origin if origin is not None else mesh.center
    if extent == "full":
        mb = mesh.bounds
        extent = ((mb[2 * ip[0]], mb[2 * ip[0] + 1]), (mb[2 * ip[1]], mb[2 * ip[1] + 1]))
    elif extent is None or extent == "near":
        bb = render.body_bounds(patches, margin=1 + margin, mesh_bounds=mesh.bounds) \
            if patches else None
        extent = _window(bb, ip, aspect) if bb is not None else None

    X, Y, triang, vals, ip = _slice_triangulation(mesh, field, normal, o, extent, patches)
    cmap = cmap or style.cmap_for(field)
    if clim is None:
        clim = render.clim_for(
            type("m", (), {"point_data": {field: vals}, "cell_data": {}})(),
            field, field=field)
    lvls = np.linspace(clim[0], clim[1], levels)

    created = ax is None
    if created:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.figure
    cf = ax.tricontourf(triang, vals, levels=lvls, cmap=cmap, extend="both")
    try:
        cf.set_edgecolor("face")            # kill contour-band seams on export
    except Exception:
        pass
    if contour_lines:
        ax.tricontour(triang, vals, levels=np.linspace(clim[0], clim[1], n_contour_lines),
                      colors="black", linewidths=0.4, alpha=0.5)

    segs = _body_segments(patches, normal, o, ip)
    if segs:
        from matplotlib.collections import LineCollection, PolyCollection
        # white fill for the body (the slice has a hole there) + crisp outline
        ax.add_collection(LineCollection(segs, colors="#111111", linewidths=1.4, zorder=5))

    axis_names = ["x", "y", "z"]
    ax.set_xlabel(f"{axis_names[ip[0]]} [m]"); ax.set_ylabel(f"{axis_names[ip[1]]} [m]")
    ax.set_aspect("equal")
    if extent is not None:
        ax.set_xlim(*extent[0]); ax.set_ylim(*extent[1])
    if title:
        ax.set_title(title)
    if add_cbar:
        cb = fig.colorbar(cf, ax=ax, extend="both", fraction=0.046, pad=0.02)
        cb.set_label(style.label_for(field))
        cb.outline.set_visible(False)
    if created and out:
        fig.savefig(out, dpi=200, bbox_inches="tight"); plt.close(fig)
    return fig, ax


def vector_field(case_or_data, out, *, vector="U", normal="z", origin=None,
                 extent=None, margin=0.6, aspect=0.55, grid=26, cmap=None,
                 clim=None, title=None, figsize=(10, 6), background=True,
                 normalize=True):
    """Down-sampled vector (quiver) map on a slice, arrows coloured by magnitude
    over a faint magnitude background. Down-sampling onto a regular grid is
    essential — drawing an arrow per cell turns into an unreadable mat.

    normalize=True (default) draws every arrow the SAME length, so the picture
    reads as *direction*, coloured by speed. This is what makes a vector map
    informative for an external flow: a true-length quiver is swamped by the
    uniform freestream and the deflection around the body (e.g. the flow
    splitting at a leading edge) becomes invisible. Set normalize=False for true
    proportional arrows when speed varies a lot (recirculation, a jet)."""
    import matplotlib.pyplot as plt
    style.use_mpl_style(grid="none")
    if isinstance(case_or_data, str):
        data = render.open_foam(case_or_data)
        mesh, patches = data["internal"], data["patches"]
    elif isinstance(case_or_data, dict):
        mesh, patches = case_or_data["internal"], case_or_data.get("patches", {})
    else:
        mesh, patches = case_or_data, {}
    naxis = _AXES.get(str(normal).lower(), 2)
    ip = [i for i in range(3) if i != naxis]
    o = origin if origin is not None else mesh.center
    if extent is None:
        bb = render.body_bounds(patches, margin=1 + margin, mesh_bounds=mesh.bounds) \
            if patches else None
        extent = _window(bb, ip, aspect) if bb is not None else None
    sl = mesh.slice(normal=normal, origin=o)
    if vector not in sl.point_data:
        sl = sl.cell_data_to_point_data()
    P = sl.points; V = np.asarray(sl.point_data[vector])
    X, Y = P[:, ip[0]], P[:, ip[1]]
    U, W = V[:, ip[0]], V[:, ip[1]]
    mag = np.linalg.norm(V, axis=1)
    if extent is None:
        extent = ((X.min(), X.max()), (Y.min(), Y.max()))
    # resample onto a regular grid for legible arrow spacing
    from scipy.interpolate import griddata
    gx = np.linspace(*extent[0], grid)
    gy = np.linspace(*extent[1], int(grid * aspect) or grid)
    GX, GY = np.meshgrid(gx, gy)
    gu = griddata((X, Y), U, (GX, GY), method="linear")
    gw = griddata((X, Y), W, (GX, GY), method="linear")
    # mask grid points inside the body (the slice has a hole there, but griddata
    # interpolates straight across it — leaving arrows floating inside the body)
    segs = _body_segments(patches, normal, o, ip)
    if segs:
        try:
            from scipy.spatial import ConvexHull
            from matplotlib.path import Path
            bpts = np.array([p for s in segs for p in s])
            hull = ConvexHull(bpts)
            poly = Path(bpts[hull.vertices])
            inside = poly.contains_points(np.column_stack([GX.ravel(), GY.ravel()]))
            inside = inside.reshape(GX.shape)
            gu[inside] = np.nan; gw[inside] = np.nan
        except Exception:
            pass
    gm = np.hypot(gu, gw)
    cmap = cmap or style.cmap_for(vector)
    fig, ax = plt.subplots(figsize=figsize)
    if background:
        bm = griddata((X, Y), mag, (GX, GY), method="linear")
        ax.pcolormesh(GX, GY, bm, cmap=cmap, shading="auto", alpha=0.30,
                      vmin=clim[0] if clim else None, vmax=clim[1] if clim else None)
    if normalize:
        # unit arrows: direction is the signal, colour is speed. Fixed display
        # length tied to the grid spacing so the field reads as a clean lattice.
        with np.errstate(invalid="ignore", divide="ignore"):
            un, wn = gu / gm, gw / gm
        q = ax.quiver(GX, GY, un, wn, gm, cmap=cmap, clim=clim, pivot="mid",
                      angles="xy", scale=grid * 1.15, scale_units="width",
                      width=0.004, headwidth=4, headlength=4.5, headaxislength=4)
        ax.text(0.015, 0.97, "arrow = direction · colour = |U|",
                transform=ax.transAxes, va="top", ha="left",
                fontsize=9, color=style.MUTED, style="italic")
    else:
        q = ax.quiver(GX, GY, gu, gw, gm, cmap=cmap, clim=clim, angles="xy",
                      scale_units="width", scale=None, width=0.0028)
    segs = _body_segments(patches, normal, o, ip)
    if segs:
        from matplotlib.collections import LineCollection
        ax.add_collection(LineCollection(segs, colors="#111111", linewidths=1.4, zorder=5))
    cb = fig.colorbar(q, ax=ax, fraction=0.046, pad=0.02)
    cb.set_label(style.label_for(vector)); cb.outline.set_visible(False)
    an = ["x", "y", "z"]
    ax.set_xlabel(f"{an[ip[0]]} [m]"); ax.set_ylabel(f"{an[ip[1]]} [m]")
    ax.set_aspect("equal"); ax.set_xlim(*extent[0]); ax.set_ylim(*extent[1])
    if title:
        ax.set_title(title)
    fig.savefig(out, dpi=200, bbox_inches="tight"); plt.close(fig)
    return out


def field_map_pair(case_or_data, field, out, *, normal="z", origin=None,
                   near_margin=0.6, wide="full", cmap=None, clim=None,
                   levels=24, contour_lines=False, suptitle=None,
                   figsize=(15.5, 5.6), aspect=0.55, separate=False):
    """Context + detail: a wide view and a near-body zoom, sharing one colour
    scale — the clean way to show both the global field and the near-body detail.

    wide:  "full" (default) shows the WHOLE mesh/domain; or a number to use that
           body-size margin instead.
    separate: if True, write the wide and near views as TWO files
              (`<out>_wide.png`, `<out>_near.png`) instead of one combined figure.
              Returns the list of paths. Otherwise writes one figure with both
              panels and a shared colorbar, and returns its path.

    Both panels always use the SAME clim so colours are directly comparable.
    """
    import matplotlib.pyplot as plt
    import matplotlib.cm as cm
    style.use_mpl_style(grid="none")
    if isinstance(case_or_data, str):
        data = render.open_foam(case_or_data)
    elif isinstance(case_or_data, dict):
        data = case_or_data
    else:
        data = {"internal": case_or_data, "patches": {}}
    mesh, patches = data["internal"], data.get("patches", {})
    naxis = _AXES.get(str(normal).lower(), 2)
    ip = [i for i in range(3) if i != naxis]

    def _near():
        bb = render.body_bounds(patches, margin=1 + near_margin, mesh_bounds=mesh.bounds) \
            if patches else None
        return _window(bb, ip, aspect) if bb is not None else None

    def _wide():
        if wide == "full":
            mb = mesh.bounds
            return ((mb[2 * ip[0]], mb[2 * ip[0] + 1]), (mb[2 * ip[1]], mb[2 * ip[1] + 1]))
        bb = render.body_bounds(patches, margin=1 + wide, mesh_bounds=mesh.bounds) \
            if patches else None
        return _window(bb, ip, aspect) if bb is not None else None

    # shared clim from the near field (where the interesting range lives)
    if clim is None:
        o = origin if origin is not None else mesh.center
        _, _, _, vals, _ = _slice_triangulation(mesh, field, normal, o, _near(), patches)
        clim = render.clim_for(
            type("m", (), {"point_data": {field: vals}, "cell_data": {}})(),
            field, field=field)

    if separate:
        base, ext = os.path.splitext(out)
        pw, pn = f"{base}_wide{ext or '.png'}", f"{base}_near{ext or '.png'}"
        field_map(data, field, pw, normal=normal, origin=origin, extent=_wide(),
                  cmap=cmap, clim=clim, levels=levels, contour_lines=contour_lines,
                  title=suptitle or "Wide view")
        field_map(data, field, pn, normal=normal, origin=origin, extent=_near(),
                  cmap=cmap, clim=clim, levels=levels, contour_lines=contour_lines,
                  title=(suptitle + " — near body") if suptitle else "Near body")
        return [pw, pn]

    fig, axes = plt.subplots(1, 2, figsize=figsize, constrained_layout=True)
    field_map(data, field, normal=normal, origin=origin, extent=_wide(),
              cmap=cmap, clim=clim, levels=levels, contour_lines=contour_lines,
              ax=axes[0], add_cbar=False, title="Wide view (full domain)")
    field_map(data, field, normal=normal, origin=origin, extent=_near(),
              cmap=cmap, clim=clim, levels=levels, contour_lines=contour_lines,
              ax=axes[1], add_cbar=False, title="Near body")
    sm = cm.ScalarMappable(cmap=cmap or style.cmap_for(field),
                           norm=plt.Normalize(*clim))
    cb = fig.colorbar(sm, ax=axes, extend="both", fraction=0.046, pad=0.02)
    cb.set_label(style.label_for(field)); cb.outline.set_visible(False)
    if suptitle:
        fig.suptitle(suptitle, fontweight="bold", x=0.01, ha="left")
    fig.savefig(out, dpi=200, bbox_inches="tight"); plt.close(fig)
    return out
