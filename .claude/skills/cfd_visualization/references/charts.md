# 2-D charts

Quantitative CFD evidence — convergence, loads, distributions — belongs in
charts, not renders. `cfdviz.charts` builds these in two flavours from the same
data: matplotlib (static, for any destination) and Plotly (interactive, for
HTML). Both use the shared palette so they match the renders and the report.

## Contents
- Parsing OpenFOAM output
- Residual convergence
- Force/moment convergence
- Cp / Cf / surface distributions
- y+ and near-wall
- Profiles (boundary layer, wake)
- Quality histograms
- General styling rules

## Parsing OpenFOAM output

- `charts.parse_residuals(log_path)` → `{"iters", "Ux", "Uy", "p", "k", ...}`
  from a solver log (`Solving for X, Initial residual = ...`). Keeps the first
  (meaningful) residual per field per step.
- `charts.parse_force_coeffs(dat_path)` → dict keyed by column header (`Cd`,
  `Cl`, `CmPitch`, `Cd(f)`, `Cd(r)`, ...) from a `forceCoeffs` `coefficient.dat`.
- For other solvers, read into numpy/pandas and pass arrays to the chart builders
  directly — they don't require OpenFOAM.

## Residual convergence

`charts.residual_plot(res, out, target=1e-5)` — semilog y, one line per field,
target residual marked. Log scale is mandatory: residuals span many decades and
a linear axis hides everything but the first few iterations. Interactive version:
`charts.plotly_residuals(res)` (hover reads exact values, legend toggles fields).

## Force/moment convergence

`charts.coeff_convergence(co, out, keys=("Cd","Cl","CmPitch"))` — stacked panels
sharing the iteration axis, each annotated with the converged value (mean over
the last `settle_frac` of the run). This makes "has it converged" *visible*. For
a drag breakdown (pressure vs viscous), plot the `Cd(f)`/`Cd(r)` or
pressure/viscous components as stacked or paired lines — avoid pie charts; they
make values hard to compare and read poorly in print.

## Cp / Cf / surface distributions

Use the dedicated helpers — they handle the trap that surface nodes on a
2-D-extruded body exist only on the span end-planes (sampling the raw patch gives
an empty or doubled curve):

```python
(xu, vu), (xl, vl) = render.wall_profile(case, "p", patch="airfoil")  # slices the
#   body at mid-span, splits upper/lower, normalises x to [0,1] chord
cpu = charts.cp_from_p(vu, U_inf=20)   # Cp = (p - p_inf)/(0.5 u_inf^2); rho=1 for
cpl = charts.cp_from_p(vl, U_inf=20)   #   kinematic OpenFOAM p, pass rho otherwise
charts.cp_distribution((xu, cpu), (xl, cpl), "out/cp.png", ref=(x_exp, cp_exp, "Exp."))
```

`cp_distribution` inverts the y-axis (suction up) by convention and overlays
reference/experimental points as markers (not lines) so measured-vs-computed is
unambiguous. For a symmetric section at zero incidence the upper and lower curves
coincide exactly — that's the correct result, not a bug. Use the same pattern
with wall shear for Cf. For an HTML report use the interactive twin
`charts.plotly_cp(upper, lower, ref=...)`; `charts.plotly_xy(series, ...)` is the
generic interactive line builder for profiles / Cf / sweeps.

## y+ and near-wall

Plot the y+ distribution over the wall (histogram or along-chord line) and state
the wall-treatment target band (y+≈1 for wall-resolved; 30–300 for wall
functions). A surface render of y+ (`render.surface_field(..., "yPlus")`)
complements the chart by showing *where* it's out of band.

## Profiles (boundary layer, wake)

Sample along a line with `mesh.sample_over_line(p0, p1)` (or `plot_over_line`)
and plot velocity vs wall-normal distance. For boundary layers, a log x-axis (y+)
with U+ reveals the law-of-the-wall structure. For wakes, plot velocity deficit
vs cross-stream position at several downstream stations as separate series.

## Quality histograms

`charts.quality_histogram(...)` — see `mesh.md`. The same builder serves any
distribution where a threshold separates good from bad. Heavy-tailed fields
(cellDeterminant, cellVolume, minTetVolume span orders of magnitude) crush a
linear histogram into one bin — pass `log_x=True`, or
`clip_percentile=99.5` which clips the x-range and *discloses* how many cells
fall outside so nothing is hidden silently.

## Force/drag breakdown

`charts.drag_breakdown({"Pressure drag": ..., "Viscous drag": ...}, out, unit=...)`
draws a horizontal bar: a stacked Total plus one bar per component, with values
and percentages annotated. A bar is usually the clearest choice — magnitudes are
easy to compare and exact values are readable, including in print. A pie is fine
too when you just want to show a couple of proportions. The same helper serves
any additive breakdown (per-component forces, energy budget terms).

## General styling rules

`style.use_mpl_style()` is applied by every builder. It layers **seaborn**'s
refined defaults underneath (whitegrid, notebook context) and then overrides with
the cfdviz tokens: Okabe–Ito series colors (colorblind-safe, used in order), thin
spines, top/right spines removed, faint horizontal gridlines, sans fonts,
vector-friendly. Pass `grid="y"|"both"|"none"` to control gridlines (default
`"y"` — horizontal only, ideal for trends). When writing a custom chart, call it
first and pull colors from `style.OKABE_ITO` / the named tokens
(`style.ACTION_BLUE`, `style.GOOD/MARGINAL/BAD`) so it matches everything else.

**Readability:** every builder uses tight layout so nothing overlaps, but verify
by eye — move a legend off the data if it collides, thin crowded tick labels, and
prefer a context+detail pair over a single cramped frame.

- Label every axis with units; sentence case ("Pressure coefficient", not
  "PRESSURE COEFFICIENT").
- Log scale whenever the data spans decades (residuals, turbulence, particle
  size).
- Don't truncate a bar/line axis baseline to exaggerate a difference.
- Annotate the converged/important value directly on the line rather than making
  the reader read it off the axis.
- Save SVG/PDF for print, PNG ≥200 DPI otherwise; Plotly for HTML (see html.md).
