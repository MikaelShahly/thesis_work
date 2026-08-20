"""Palette, colormaps, and styling shared by every cfdviz figure.

The single most common way CFD figures look amateurish is colormap choice
(rainbow/jet) and inconsistent fonts/colors between the 3-D renders and the 2-D
charts in the same report. This module centralises both so a whole report looks
like it came from one hand.

Colors mirror the `html-report` design system so static figures, interactive
charts, and the surrounding HTML share one identity.
"""
from __future__ import annotations

# ── Report-matched palette (mirrors html-report/design-system.md) ───────────
INK = "#212121"          # default text
MUTED = "#93939f"        # metadata / de-emphasised
SLATE = "#75758a"        # tertiary text / separators
HAIRLINE = "#d9d9dd"     # gridlines, light rules
ACTION_BLUE = "#1863dc"  # links / primary series
CORAL = "#ff7759"        # accent / secondary series / annotation marker
DEEP_GREEN = "#003c33"
DARK_NAVY = "#071829"
CANVAS = "#ffffff"

# Status colors — use for pass/marginal/fail of a metric (residuals, y+, quality).
GOOD, GOOD_SOFT = "#1f7a4d", "#e6f4ec"
MARGINAL, MARGINAL_SOFT = "#b45309", "#fbeede"
BAD, BAD_SOFT = "#b91c1c", "#f9e6e6"

# Okabe–Ito categorical palette (colorblind-safe). Use IN ORDER for series;
# if you need more than 8 categories, the chart is doing too much.
OKABE_ITO = [
    "#0072B2",  # blue
    "#E69F00",  # orange
    "#009E73",  # bluish green
    "#CC79A7",  # reddish purple
    "#56B4E9",  # sky blue
    "#D55E00",  # vermillion
    "#F0E442",  # yellow
    "#000000",  # black
]

# Font stacks. Matplotlib uses whatever's installed (graceful fallback); the
# report's Inter/Space Grotesk arrive via CDN in the HTML and in the Plotly
# template below so interactive charts match the page exactly.
SANS_STACK = ["Inter", "Helvetica Neue", "Arial", "DejaVu Sans", "sans-serif"]
PLOTLY_FONT = 'Inter, "Helvetica Neue", Arial, sans-serif'


# ── Colormap selection: the heart of looking professional ───────────────────
# Pick by what the field MEANS, not by taste. Diverging maps must be centred on
# their neutral value (0 for vorticity, freestream for Cp/pressure) or they lie.
CMAP = {
    # sequential, perceptually uniform — magnitudes with a meaningful zero floor
    "velocity": "viridis",       # |U|, speed
    "turbulence": "inferno",     # k, nut, omega — energy-like, dark→bright
    "temperature": "inferno",
    "scalar": "viridis",         # generic passive scalar / concentration
    "wall_distance": "cividis",
    # diverging — fields with a meaningful centre (sign matters)
    "pressure": "RdBu_r",        # p, Cp — centre on freestream (see diverging_clim)
    "vorticity": "RdBu_r",       # centre on 0
    "diverging": "RdBu_r",
    # mesh quality (sequential; pair with threshold highlight for bad cells)
    "quality": "cividis",
    "quality_warn": "inferno",   # when "high == bad" reads naturally as hot
}

# Fields where larger value == worse mesh quality (used to colour/threshold).
HIGHER_IS_WORSE = {
    "skewness", "nonOrthoAngle", "aspectRatio", "cellAspectRatio",
    "cellVolumeRatio", "faceWeight_inv",
}
# Fields where smaller value == worse (collapsing cells).
LOWER_IS_WORSE = {
    "cellDeterminant", "minTetVolume", "minPyrVolume", "faceWeight", "cellVolume",
}

# Human labels + units for common OpenFOAM / CFD fields. Used for scalar-bar and
# axis titles so the reader never has to decode a variable name.
FIELD_LABEL = {
    "U": "Velocity magnitude (m/s)",
    "Umag": "Velocity magnitude (m/s)",
    "p": "Pressure (m²/s²)",
    "p_rgh": "Pressure (m²/s²)",
    "Cp": "Pressure coefficient $C_p$",
    "k": "Turbulent kinetic energy (m²/s²)",
    "omega": "Specific dissipation ω (1/s)",
    "epsilon": "Dissipation ε (m²/s³)",
    "nut": "Turbulent viscosity ν_t (m²/s)",
    "T": "Temperature (K)",
    "vorticity": "Vorticity (1/s)",
    "wallDistance": "Wall distance (m)",
    "yPlus": "y⁺",
    "skewness": "Skewness",
    "nonOrthoAngle": "Non-orthogonality (°)",
    "aspectRatio": "Aspect ratio",
    "cellAspectRatio": "Cell aspect ratio",
    "cellVolume": "Cell volume (m³)",
    "cellVolumeRatio": "Cell volume ratio",
    "cellDeterminant": "Cell determinant",
    "faceWeight": "Face weight",
    "minTetVolume": "Min tet volume (m³)",
}


def cmap_for(field: str, kind: str | None = None) -> str:
    """Best colormap for a field. `kind` overrides auto-detection by name."""
    if kind:
        return CMAP.get(kind, kind)
    f = field.lower()
    if any(s in f for s in ("pressure", "_p", "cp")) or f == "p":
        return CMAP["pressure"]
    if "vort" in f:
        return CMAP["vorticity"]
    if any(s in f for s in ("vel", "umag", "speed")) or f == "u":
        return CMAP["velocity"]
    if any(s in f for s in ("nut", "omega", "epsilon", "tke")) or f == "k":
        return CMAP["turbulence"]
    if "temp" in f or f == "t":
        return CMAP["temperature"]
    if "walldist" in f:
        return CMAP["wall_distance"]
    if field in HIGHER_IS_WORSE or field in LOWER_IS_WORSE:
        return CMAP["quality"]
    return CMAP["scalar"]


def label_for(field: str) -> str:
    """Human-readable label (with units) for a field name; falls back to the name."""
    return FIELD_LABEL.get(field, field)


def is_diverging(field: str) -> bool:
    f = field.lower()
    return f == "p" or "pressure" in f or "cp" in f or "vort" in f


# ── matplotlib rcParams ──────────────────────────────────────────────────────
def use_mpl_style(scale: float = 1.0, grid: str = "y"):
    """Apply the cfdviz matplotlib style. Call once before plotting.

    Clean editorial look: thin spines, faint gridlines, sans fonts,
    vector-friendly. Layers seaborn's polished defaults underneath (if seaborn is
    installed) and then overrides them with the cfdviz tokens, so charts get
    seaborn's refinement while staying on-brand and consistent with the 3-D
    renders and the report.

    `scale` bumps all font sizes for dense multi-panel figures or slides.
    `grid` controls gridlines: "y" (default, horizontal only — best for trends
    and residuals), "both", or "none".
    """
    import matplotlib as mpl
    # Seaborn underlay: refined whitegrid base + Okabe–Ito palette. Optional —
    # the style is complete without it, this just elevates the baseline.
    try:
        import seaborn as sns
        sns.set_theme(style="whitegrid", context="notebook",
                      font="sans-serif", rc={"axes.facecolor": "white"})
        sns.set_palette(OKABE_ITO)
    except Exception:
        pass

    s = scale
    grid_on = grid != "none"
    grid_axis = "y" if grid == "y" else "both"
    mpl.rcParams.update({
        "figure.dpi": 120,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
        "savefig.facecolor": "white",
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "font.family": "sans-serif",
        "font.sans-serif": SANS_STACK,
        "font.size": 11 * s,
        "axes.titlesize": 13 * s,
        "axes.titleweight": "bold",
        "axes.labelsize": 12 * s,
        "axes.labelcolor": INK,
        "axes.edgecolor": SLATE,
        "axes.linewidth": 0.8,
        "axes.titlecolor": INK,
        "text.color": INK,
        "axes.grid": grid_on,
        "axes.grid.axis": grid_axis,
        "grid.color": HAIRLINE,
        "grid.linewidth": 0.6,
        "grid.alpha": 0.7,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.axisbelow": True,
        "xtick.color": SLATE,
        "ytick.color": SLATE,
        "xtick.labelcolor": INK,
        "ytick.labelcolor": INK,
        "xtick.labelsize": 10 * s,
        "ytick.labelsize": 10 * s,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "legend.fontsize": 10 * s,
        "legend.frameon": False,
        "lines.linewidth": 1.8,
        "lines.solid_capstyle": "round",
        "axes.prop_cycle": mpl.cycler(color=OKABE_ITO),
        "figure.autolayout": False,
    })


# ── Plotly template (matches the report exactly) ─────────────────────────────
def plotly_template():
    """A Plotly template tuned to the html-report design system.

    Returns a plotly.graph_objects.layout.Template. Register + use it so every
    interactive chart in a report shares the page's font, ink, gridlines, and
    accent colors:

        import plotly.io as pio
        pio.templates["cfdviz"] = cfdviz.style.plotly_template()
        pio.templates.default = "cfdviz"
    """
    import plotly.graph_objects as go

    axis = dict(
        showgrid=True, gridcolor=HAIRLINE, gridwidth=1,
        zeroline=False, linecolor=SLATE, linewidth=1,
        ticks="outside", tickcolor=SLATE, ticklen=5,
        title=dict(font=dict(size=15, color=INK)),
        tickfont=dict(size=12, color=INK),
        showline=True, mirror=False,
    )
    return go.layout.Template(
        layout=dict(
            font=dict(family=PLOTLY_FONT, size=13, color=INK),
            paper_bgcolor=CANVAS,
            plot_bgcolor=CANVAS,
            colorway=OKABE_ITO,
            title=dict(font=dict(family=PLOTLY_FONT, size=19, color=INK), x=0.0, xanchor="left"),
            xaxis=axis, yaxis=axis,
            legend=dict(bgcolor="rgba(255,255,255,0)", font=dict(size=12, color=INK),
                        borderwidth=0),
            margin=dict(l=70, r=30, t=60, b=60),
            hoverlabel=dict(font=dict(family=PLOTLY_FONT, size=12), bgcolor="white",
                            bordercolor=HAIRLINE),
            colorscale=dict(sequential="Viridis", diverging="RdBu"),
        )
    )
