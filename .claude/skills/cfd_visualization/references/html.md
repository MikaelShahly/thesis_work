# Visualizations in an HTML report

When the deliverable is an HTML report, the `html-report` skill owns the page
(structure, design system, single self-contained file). This skill owns the
figures inside it. The two are designed to fit together — read this before
producing figures for HTML so they drop in cleanly and look native to the page.

## The division of labour

- **Field/mesh renders → static PNG**, embedded as base64 data URIs. 3-D renders
  don't benefit from interactivity in a report and a live WebGL scene is heavy
  and fragile; a crisp high-DPI PNG is the professional choice. Render large
  (the toolkit supersamples) so it stays sharp on hi-dpi screens.
- **Quantitative charts → interactive Plotly.** Residuals, force/moment
  convergence, Cp, y+, profiles, quality distributions become *explorable*:
  hover for exact values, zoom into the convergence tail, toggle series. This is
  the single biggest reason an HTML report beats a PDF — use it. This is the
  "symmetry" between the two skills: charts that would be flat images in a paper
  become interactive here. Helpers: `charts.plotly_residuals`, `plotly_coeffs`,
  `plotly_cp`, and the generic `plotly_xy(series, ...)` (for y+, profiles, Cf,
  and anything else) — all on the shared `cfdviz` template, so they match the
  page. Build any other interactive chart directly on `style.plotly_template()`.

## Match the page, automatically

`cfdviz` is pre-tuned to the html-report design system, so figures share the
page's identity without manual fiddling:

- The Plotly template (`style.plotly_template()`, auto-registered by the
  `charts.plotly_*` builders) uses the report's Inter font, ink `#212121`,
  hairline gridlines, action-blue/coral accents, and Okabe–Ito series colors.
- The matplotlib style and the pyvista renders use the *same* palette, so a
  static render, an interactive chart, and the surrounding prose look like one
  document.
- Status colors (`style.GOOD/MARGINAL/BAD` + their soft fills) match the report's
  status chips — use `charts.status(value, ...)` to classify a metric and color a
  chip/cell the same way the page would.

## Embedding — follow html-report's conventions

The `html-report` skill's *Embedding conventions* are the rule; this is how CFD
output maps onto them.

**Interactive chart (Plotly):**

```python
from cfdviz import charts
fig = charts.plotly_residuals(charts.parse_residuals("log.simpleFoam"))
frag_first = charts.plotly_div(fig, include_js="cdn")   # FIRST chart loads plotly.js from CDN
# later charts on the same page:
frag_more  = charts.plotly_div(fig2, include_js=False)  # reuse the already-loaded library
```

`plotly_div` returns a self-contained HTML fragment (a `<div>` + its script).
Load the library once per page (`include_js="cdn"` on the first figure, `False`
after) — CDN is explicitly allowed by html-report; bundling it inline once also
works for true offline self-containment. Drop the fragments straight into the
report body where the figure belongs.

**Static render (PNG):** base64-encode and embed as `<img>`. The html-report
skill's `scripts/inline.py` does exactly this — reuse it:

```python
import base64
b64 = base64.b64encode(open("out/pressure.png","rb").read()).decode()
img = f'<img src="data:image/png;base64,{b64}" alt="Pressure field, mid-span">'
```

Give every figure a real `alt`/caption describing what it shows and the operating
point — the caption carries the finding.

**Raw data behind a chart:** if you also want the numbers available (download,
inspection), put them in a `<script type="application/json" id="...">` block per
html-report's convention; the chart can read from it, or it can simply document
the figure.

## Practical tips

- Don't mix a static matplotlib PNG of a chart with interactive Plotly charts on
  the same page — pick interactive for HTML and keep it consistent.
- Keep each Plotly figure responsive (`config={"responsive": True}`, already set
  by `plotly_div`) so it fits the report's column width on any screen.
- A handful of interactive charts is great; fifty is slow. If a report has many
  small trends, a static small-multiples PNG can be the clearer, lighter choice.
- For an animation (e.g. convergence of the field), an embedded GIF/MP4 via
  `imageio` is simplest and self-contained; see `pyvista-recipes.md`.
