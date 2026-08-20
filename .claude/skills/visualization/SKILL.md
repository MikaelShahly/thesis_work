---
name: visualization
description: >
  Use this whenever producing a figure, plot, chart, or visualization —
  especially for a report or paper. Produces publication-quality figures that
  are clean, accurate, colorblind-safe, and immediately understandable, suitable
  for a peer-reviewed journal. Covers colour palettes, layout, typography,
  accessibility, uncertainty, and choosing the output format for the destination
  (SVG for HTML, PDF for LaTeX, high-DPI PNG/TIFF for raster). Apply it to every
  figure and run the pre-output checklist before returning the figure. Do NOT use
  for tables of numbers, UI mockups, or diagrams that carry no data. Invoke without arguments.
---

# Publication-quality figures

Produce figures that are clean, accurate, and immediately understandable. Every
plot should be suitable for a peer-reviewed journal — a reader should grasp all
the information at a glance, with no clutter, overlap, or ambiguity.

## Core principles

1. **Clarity** — Information is understandable at a glance; nothing competes for attention.
2. **Accuracy** — Data is represented truthfully and without distortion.
3. **Accessibility** — Figures are interpretable by all readers, including those with colour vision deficiencies.
4. **Professionalism** — Clean, polished appearance appropriate for a peer-reviewed journal.

## Color

- Use colour to encode data, not to decorate. If colour carries no information, remove it.
- Use colorblind-friendly palettes throughout.
- **Categorical** → Okabe–Ito (up to 8 categories; if you need more, rethink the chart).
- **Sequential** → Viridis (Matplotlib default) or Cividis. Plasma, Inferno, or Magma are acceptable for aesthetic variation.
- **Diverging** → RdBu, RdYlBu, PuOr, or BrBG. Avoid RdYlGn or any red–green diverging map (unreadable for the most common colour vision deficiency).

Okabe–Ito palette:

```python
okabe_ito = {
    'orange':          '#E69F00',  # (230, 159, 0)
    'sky_blue':        '#56B4E9',  # (86, 180, 233)
    'bluish_green':    '#009E73',  # (0, 158, 115)
    'yellow':          '#F0E442',  # (240, 228, 66)
    'blue':            '#0072B2',  # (0, 114, 178)
    'vermillion':      '#D55E00',  # (213, 94, 0)
    'reddish_purple':  '#CC79A7',  # (204, 121, 167)
    'black':           '#000000',  # (0, 0, 0)
}
```

## Layout

- Strip non-data ink: remove gridlines, borders, and backgrounds that carry no information.
- Never allow overlapping data elements, labels, or markers — adjust spacing, jitter, or chart type instead.
- Aspect ratio fits the data: time series wider than tall (≈3:1 to 2:1); comparisons can be squarer.

## Typography & labels

- Always label axes — never make the reader infer what a number means.
- Sentence case for axis labels: "Time (hours)", not "TIME (HOURS)".
- Include units in parentheses when relevant.
- Avoid abbreviations unless space-constrained; define any you use in the caption.
- Use one font consistently across all text (axes, ticks, labels, legend, annotations). 
- All text legible at standard zoom.

## Accessibility

- Maintain sufficient contrast between data elements and background.

## Uncertainty

- Show uncertainty when data is uncertain: error bars, confidence intervals, or ranges.

## Output format

- Prefer vector for plots; use raster (PNG, TIFF — never JPEG) for images. Reserve TIFF for explicit print export, as it does not render in browsers.
- Raster output at 300–600 DPI minimum.
- Decide the exact format based on the desired output format (SVG for HTML, PDF for LaTeX, etc.).

## Pre-output checklist

Before returning any figure, confirm:

- [ ] No clutter; no overlapping elements.
- [ ] All figures are suitably sized so the information is clear (not too small to convey the information).
- [ ] All axes labelled, with units where relevant.
- [ ] Text legible at standard zoom.
- [ ] A single font used for all visualizations. 
- [ ] Colour is colorblind-safe and information-bearing.
- [ ] Legend is complete and does not obscure data.
- [ ] Uncertainty shown where data is uncertain.
- [ ] Correct format (vector; or PNG/TIFF, never JPEG).
- [ ] Visualizations, fonts, etc. are styled consistently with the destination output format they are used in (LaTeX report, HTML report, etc.).
