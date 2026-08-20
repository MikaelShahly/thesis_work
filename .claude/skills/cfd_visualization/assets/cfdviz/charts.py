"""2-D charts for CFD + OpenFOAM log/data parsers.

Two output paths from the same data:
  * matplotlib  -> static SVG/PNG for any destination (LaTeX, slides, PNG embed)
  * plotly      -> interactive HTML fragment for an html-report (hover, zoom,
                   toggle series). Use this path when the deliverable is HTML so
                   residuals/coefficients/Cp become explorable, not flat images.

Both share the cfdviz palette so they look identical to the 3-D renders and the
report around them.
"""
from __future__ import annotations
import re
import numpy as np
from . import style


# ── OpenFOAM parsers ─────────────────────────────────────────────────────────
def parse_residuals(log_path, fields=("Ux", "Uy", "Uz", "p", "k", "omega", "epsilon", "nut")):
    """Parse 'Solving for X, Initial residual = ...' from a solver log.
    Returns {"iters": [...], "<field>": [...]} keeping only fields that appear.
    Takes the FIRST residual per field per time step (the meaningful one)."""
    times, data = [], {f: [] for f in fields}
    cur, seen = None, set()
    with open(log_path, errors="ignore") as fh:
        for line in fh:
            m = re.match(r"^Time = (\S+)", line)
            if m:
                cur = m.group(1); seen = set()
                try:
                    times.append(float(cur))
                except ValueError:
                    times.append(len(times) + 1)
                continue
            m = re.search(r"Solving for (\w+),\s*Initial residual = ([0-9.eE+\-]+)", line)
            if m and cur is not None:
                fld, val = m.group(1), float(m.group(2))
                if fld in data and fld not in seen:
                    data[fld].append(val); seen.add(fld)
    n = len(times)
    out = {"iters": np.array(times[:n])}
    for f in fields:
        if data[f]:
            v = data[f]
            v = v + [v[-1]] * (n - len(v)) if len(v) < n else v[:n]
            out[f] = np.array(v)
    return out


def parse_force_coeffs(dat_path):
    """Parse an OpenFOAM forceCoeffs coefficient.dat. Returns a dict of columns
    keyed by header name (Cd, Cl, CmPitch, Cd(f), Cd(r), …) plus 'time'."""
    header, rows = None, []
    with open(dat_path, errors="ignore") as fh:
        for line in fh:
            s = line.strip()
            if s.startswith("#"):
                cols = s.lstrip("#").split()
                if cols and cols[0].lower() in ("time", "#"):
                    header = cols
                elif cols and "Cd" in cols:
                    header = cols
                continue
            if not s:
                continue
            rows.append([float(x) for x in s.split()])
    arr = np.array(rows)
    if header is None or len(header) != arr.shape[1]:
        header = ["time"] + [f"c{i}" for i in range(1, arr.shape[1])]
    return {h: arr[:, i] for i, h in enumerate(header)}


def _time_axis(coeffs, n):
    """The iteration/time column, found case-insensitively (OpenFOAM writes
    'Time', we don't want a silent fallback to arange that mislabels the x-axis)."""
    for k in coeffs:
        if k.lower() in ("time", "iter", "iteration", "step"):
            return coeffs[k]
    return np.arange(1, n + 1)


# ── matplotlib charts ────────────────────────────────────────────────────────
def residual_plot(res, out, *, target=1e-5, title="Residual convergence", scale=1.0):
    """Semilog residual history. `res` is the dict from parse_residuals."""
    import matplotlib.pyplot as plt
    style.use_mpl_style(scale)
    fig, ax = plt.subplots(figsize=(8.5, 5))
    it = res["iters"]
    series = [k for k in res if k != "iters"]
    for k, c in zip(series, style.OKABE_ITO):
        ax.semilogy(it, res[k], label=k, color=c)
    if target:
        ax.axhline(target, ls="--", lw=1, color=style.SLATE,
                   label=f"target {target:g}")
    ax.set_xlabel("Iteration"); ax.set_ylabel("Initial residual")
    ax.set_title(title)
    ax.legend(ncol=min(4, len(series) + 1), loc="upper right")
    ax.grid(True, which="both", axis="y", alpha=0.4)
    fig.tight_layout(); fig.savefig(out); plt.close(fig)
    return out


def coeff_convergence(coeffs, out, *, keys=("Cd", "Cl", "CmPitch"),
                      title="Force-coefficient convergence", scale=1.0,
                      settle_frac=0.2):
    """Stacked convergence panels for force coefficients, annotating the
    converged (mean-over-last-settle_frac) value on each."""
    import matplotlib.pyplot as plt
    style.use_mpl_style(scale)
    keys = [k for k in keys if k in coeffs]
    t = _time_axis(coeffs, len(coeffs[keys[0]]))
    fig, axes = plt.subplots(len(keys), 1, figsize=(8.5, 2.4 * len(keys)), sharex=True)
    if len(keys) == 1:
        axes = [axes]
    for ax, k, c in zip(axes, keys, style.OKABE_ITO):
        y = coeffs[k]
        ax.plot(t, y, color=c)
        n = max(1, int(len(y) * settle_frac))
        val = float(np.mean(y[-n:]))
        ax.axhline(val, ls="--", lw=0.9, color=c, alpha=0.6)
        ax.set_ylabel(k)
        ax.annotate(f"{k} = {val:.5g}", xy=(0.98, 0.9), xycoords="axes fraction",
                    ha="right", va="top", color=c,
                    bbox=dict(boxstyle="round,pad=0.3", fc="white",
                              ec=c, alpha=0.9, lw=1))
    axes[-1].set_xlabel("Iteration")
    fig.suptitle(title, fontweight="bold", x=0.02, ha="left")
    fig.align_ylabels(axes)
    fig.tight_layout(); fig.savefig(out); plt.close(fig)
    return out


def quality_histogram(values, out, *, field="quality", threshold=None,
                      higher_bad=None, title=None, scale=1.0, bins=60, log_y=True,
                      xlim=None, log_x=False, clip_percentile=None):
    """Histogram of a mesh-quality field with the acceptance threshold marked and
    the failing tail shaded red — turns a wall of checkMesh numbers into a glance.

    Mesh-quality fields are often heavy-tailed (cellDeterminant, cellVolume,
    minTetVolume span orders of magnitude), which crushes a linear histogram into
    one bin. Handle that with:
      log_x=True            log-spaced bins / log x-axis (best for positive
                            wide-range fields)
      clip_percentile=99.5  clip the x-range to this percentile and DISCLOSE how
                            many cells fall outside (so nothing is hidden silently)
      xlim=(lo, hi)         explicit x-range
    `higher_bad` defaults from the field name (style.HIGHER/LOWER_IS_WORSE)."""
    import matplotlib.pyplot as plt
    values = np.asarray(values).ravel()
    values = values[np.isfinite(values)]
    if higher_bad is None:
        higher_bad = field not in style.LOWER_IS_WORSE
    style.use_mpl_style(scale)
    fig, ax = plt.subplots(figsize=(8.5, 4.8))

    n_total = values.size
    note = None
    plot_vals = values
    if clip_percentile is not None and xlim is None:
        hi = np.percentile(values, clip_percentile)
        lo = values.min()
        n_out = int(np.sum(values > hi))
        plot_vals = values[values <= hi]
        xlim = (lo, hi)
        if n_out:
            note = f"{n_out:,} of {n_total:,} cells > {hi:.3g} not shown"
    if log_x:
        pos = plot_vals[plot_vals > 0]
        b = np.logspace(np.log10(pos.min()), np.log10(pos.max()), bins) if pos.size else bins
        bin_edges = b
    else:
        bin_edges = bins
    counts, edges, patches = ax.hist(plot_vals, bins=bin_edges, color=style.ACTION_BLUE,
                                     alpha=0.85, edgecolor="white", linewidth=0.3)
    if threshold is not None:
        ax.axvline(threshold, color=style.BAD, lw=1.6, ls="--",
                   label=f"threshold {threshold:g}")
        for c, p in zip(edges[:-1], patches):
            if (higher_bad and c >= threshold) or (not higher_bad and c < threshold):
                p.set_facecolor(style.BAD)
        ax.legend(loc="upper right")
    ax.set_xlabel(style.label_for(field)); ax.set_ylabel("Cell count")
    if log_y:
        ax.set_yscale("log")
    if log_x:
        ax.set_xscale("log")
    if xlim:
        ax.set_xlim(*xlim)
    if note:
        ax.annotate(note, xy=(0.98, 0.02), xycoords="axes fraction", ha="right",
                    va="bottom", fontsize=9 * scale, color=style.MUTED,
                    style="italic")
    ax.set_title(title or f"{style.label_for(field)} distribution")
    fig.tight_layout(); fig.savefig(out); plt.close(fig)
    return out


def drag_breakdown(components, out, *, total_label="Total", title="Drag breakdown",
                   unit="", scale=1.0, horizontal=True):
    """Horizontal stacked + itemised bar of a force/drag breakdown (e.g. pressure
    vs viscous, or per-component). `components` is an ordered dict
    {label: value}. A bar — never a pie: bars let the reader compare magnitudes
    and read exact values, which pies make hard, especially in print.

    Shows each component as its own bar plus a stacked Total bar, with values and
    percentages annotated. Returns the path."""
    import matplotlib.pyplot as plt
    style.use_mpl_style(scale, grid="x" if horizontal else "y")
    labels = list(components.keys()); vals = np.array([components[k] for k in labels])
    total = float(vals.sum())
    fig, ax = plt.subplots(figsize=(8.5, 0.7 * (len(labels) + 1) + 1.5))
    colors = style.OKABE_ITO
    y = np.arange(len(labels) + 1)[::-1]
    # stacked total bar on top row
    left = 0.0
    for v, c, lab in zip(vals, colors, labels):
        ax.barh(y[0], v, left=left, color=c, edgecolor="white")
        if v / max(total, 1e-30) > 0.06:
            ax.text(left + v / 2, y[0], f"{100*v/total:.0f}%", ha="center",
                    va="center", color="white", fontsize=10 * scale, fontweight="bold")
        left += v
    # individual component bars
    for i, (v, c, lab) in enumerate(zip(vals, colors, labels), start=1):
        ax.barh(y[i], v, color=c, edgecolor="white")
        ax.text(v, y[i], f"  {v:.4g}{(' ' + unit) if unit else ''}", va="center",
                ha="left", fontsize=10 * scale, color=style.INK)
    ax.set_yticks(y)
    ax.set_yticklabels([total_label] + labels)
    ax.set_xlabel(f"Contribution{(' (' + unit + ')') if unit else ''}")
    ax.set_title(title)
    ax.text(total, y[0], f"  {total:.4g}{(' ' + unit) if unit else ''}", va="center",
            ha="left", fontsize=10 * scale, color=style.INK, fontweight="bold")
    ax.margins(x=0.18)
    fig.tight_layout(); fig.savefig(out); plt.close(fig)
    return out


def cp_from_p(p, u_inf, p_inf=0.0, rho=1.0):
    """Pressure coefficient. For incompressible OpenFOAM, p is kinematic (m²/s²)
    and rho=1: Cp = (p - p_inf) / (0.5 u_inf²). For dimensional p, pass rho."""
    return (np.asarray(p) - p_inf) / (0.5 * rho * u_inf ** 2)


def cp_distribution(upper, lower, out, *, title="Pressure coefficient",
                    xlabel="x / c", ref=None, scale=1.0):
    """Plot Cp(x/c) with the y-axis inverted (suction up) — the canonical airfoil
    surface-loading figure. `upper`/`lower` are (x, cp) tuples for the two
    surfaces (get them from render.wall_profile). `ref` optionally overlays
    (x, cp, label) experimental/reference points as markers."""
    import matplotlib.pyplot as plt
    style.use_mpl_style(scale)
    fig, ax = plt.subplots(figsize=(8.5, 5))
    ax.plot(upper[0], upper[1], color=style.OKABE_ITO[0], label="Upper surface")
    ax.plot(lower[0], lower[1], color=style.OKABE_ITO[1], label="Lower surface")
    if ref is not None:
        ax.plot(ref[0], ref[1], "o", color=style.INK, ms=4, mfc="white",
                mew=0.8, label=ref[2] if len(ref) > 2 else "Reference")
    ax.axhline(0, color=style.HAIRLINE, lw=0.8)
    ax.set_xlabel(xlabel); ax.set_ylabel("$C_p$")
    ax.invert_yaxis()
    ax.set_title(title); ax.legend()
    fig.tight_layout(); fig.savefig(out); plt.close(fig)
    return out


def xy_plot(series, out, *, xlabel="x", ylabel="y", title=None, scale=1.0,
            invert_y=False, equal_x=False, markers=False):
    """Generic styled line plot. `series` is a list of (x, y, label) tuples.
    Used for Cp/Cf distributions (invert_y for Cp), boundary-layer profiles, etc."""
    import matplotlib.pyplot as plt
    style.use_mpl_style(scale)
    fig, ax = plt.subplots(figsize=(8.5, 5))
    for (x, y, lbl), c in zip(series, style.OKABE_ITO):
        ax.plot(x, y, label=lbl, color=c, marker="o" if markers else None,
                ms=3, mfc=c, mec="white", mew=0.4)
    ax.set_xlabel(xlabel); ax.set_ylabel(ylabel)
    if title:
        ax.set_title(title)
    if invert_y:
        ax.invert_yaxis()
    if len([s for s in series if s[2]]) > 1:
        ax.legend()
    fig.tight_layout(); fig.savefig(out); plt.close(fig)
    return out


# ── Plotly interactive (for html-report symmetry) ────────────────────────────
def _register_plotly():
    import plotly.io as pio
    if "cfdviz" not in pio.templates:
        pio.templates["cfdviz"] = style.plotly_template()
    pio.templates.default = "cfdviz"


def plotly_residuals(res, *, target=1e-5, title="Residual convergence"):
    """Interactive residual figure. Returns a plotly Figure (call plotly_div to
    embed). Log-y, hover shows exact residuals, legend toggles series."""
    import plotly.graph_objects as go
    _register_plotly()
    fig = go.Figure()
    it = res["iters"]
    for k in [k for k in res if k != "iters"]:
        fig.add_trace(go.Scatter(x=it, y=res[k], mode="lines", name=k))
    if target:
        fig.add_hline(y=target, line_dash="dash", line_color=style.SLATE,
                      annotation_text=f"target {target:g}", annotation_position="right")
    fig.update_yaxes(type="log", title="Initial residual")
    fig.update_xaxes(title="Iteration")
    fig.update_layout(title=title, hovermode="x unified")
    return fig


def plotly_coeffs(coeffs, *, keys=("Cd", "Cl", "CmPitch"),
                  title="Force-coefficient convergence"):
    """Interactive stacked coefficient convergence (shared x, hover unified)."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    _register_plotly()
    keys = [k for k in keys if k in coeffs]
    t = _time_axis(coeffs, len(coeffs[keys[0]]))
    fig = make_subplots(rows=len(keys), cols=1, shared_xaxes=True,
                        vertical_spacing=0.06, subplot_titles=keys)
    for i, (k, c) in enumerate(zip(keys, style.OKABE_ITO), start=1):
        fig.add_trace(go.Scatter(x=t, y=coeffs[k], mode="lines", name=k,
                                 line=dict(color=c)), row=i, col=1)
    fig.update_xaxes(title="Iteration", row=len(keys), col=1)
    fig.update_layout(title=title, showlegend=False, height=240 * len(keys))
    return fig


def plotly_xy(series, *, xlabel="x", ylabel="y", title=None, invert_y=False,
              log_y=False, markers=False, hovermode="x unified"):
    """Generic interactive line/scatter figure. `series` is a list of
    (x, y, label) tuples. Covers Cp/Cf distributions, boundary-layer & wake
    profiles, sweeps — the interactive counterpart of charts.xy_plot. Returns a
    plotly Figure (embed with plotly_div)."""
    import plotly.graph_objects as go
    _register_plotly()
    fig = go.Figure()
    mode = "lines+markers" if markers else "lines"
    for (x, y, lbl), c in zip(series, style.OKABE_ITO):
        fig.add_trace(go.Scatter(x=list(x), y=list(y), mode=mode, name=lbl,
                                 line=dict(color=c)))
    fig.update_xaxes(title=xlabel)
    fig.update_yaxes(title=ylabel, autorange="reversed" if invert_y else True,
                     type="log" if log_y else "linear")
    fig.update_layout(title=title, hovermode=hovermode,
                      showlegend=len([s for s in series if s[2]]) > 1)
    return fig


def plotly_cp(upper, lower, *, ref=None, title="Pressure coefficient",
              xlabel="x / c"):
    """Interactive Cp(x/c) with inverted y (suction up) — the interactive twin of
    cp_distribution. `upper`/`lower` are (x, cp) tuples; `ref` optional
    (x, cp, label) experimental markers. Returns a plotly Figure."""
    import plotly.graph_objects as go
    _register_plotly()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=list(upper[0]), y=list(upper[1]), mode="lines",
                             name="Upper surface", line=dict(color=style.OKABE_ITO[0])))
    fig.add_trace(go.Scatter(x=list(lower[0]), y=list(lower[1]), mode="lines",
                             name="Lower surface", line=dict(color=style.OKABE_ITO[1])))
    if ref is not None:
        fig.add_trace(go.Scatter(x=list(ref[0]), y=list(ref[1]), mode="markers",
                                 name=ref[2] if len(ref) > 2 else "Reference",
                                 marker=dict(color=style.INK, size=6, symbol="circle-open")))
    fig.update_xaxes(title=xlabel)
    fig.update_yaxes(title="C_p", autorange="reversed")
    fig.update_layout(title=title, hovermode="x unified")
    return fig


def plotly_div(fig, *, include_js="cdn", div_id=None):
    """Render a plotly Figure to a self-contained HTML fragment for embedding in
    an html-report. `include_js="cdn"` loads plotly.js from CDN (allowed by the
    html-report skill); use "cdn" once per page and False for later figures to
    avoid reloading the library.
    Returns an HTML string — drop it straight into the report body."""
    return fig.to_html(full_html=False, include_plotlyjs=include_js,
                       div_id=div_id, config={"displaylogo": False, "responsive": True})


# ── status helper ────────────────────────────────────────────────────────────
def status(value, good_below=None, marginal_below=None, higher_is_worse=True):
    """Classify a metric into ('good'|'marginal'|'bad', color, soft_color) so a
    report can colour chips/cells consistently with the design system."""
    if not higher_is_worse:
        value = -value
        good_below = None if good_below is None else -good_below
        marginal_below = None if marginal_below is None else -marginal_below
    if good_below is not None and value <= good_below:
        return ("good", style.GOOD, style.GOOD_SOFT)
    if marginal_below is not None and value <= marginal_below:
        return ("marginal", style.MARGINAL, style.MARGINAL_SOFT)
    return ("bad", style.BAD, style.BAD_SOFT)
