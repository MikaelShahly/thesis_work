---
name: html-report
description: Use this skill whenever generating an HTML report as the output deliverable. Triggers include requests for a report rendered as HTML, a self-contained .html document for viewing in a browser, or a styled web-based report (as opposed to PDF, Word, LaTeX, or other formats). This skill governs the visual design system and the rules for producing a single self-contained HTML file. Do NOT use for general HTML/web app development, marketing pages, dashboards, or interactive applications — only for report-style deliverables. Invoke without arguments.
---

# HTML Report

This skill governs the format and visual design of HTML report deliverables. Report content, section structure, and ordering come from the surrounding instructions, not from this skill. This skill answers two questions: how the file is built, and how it looks.

## Output

The report is a single HTML file. Opening it directly (from a URL, from disk, etc.) must render the full report with no missing assets. The reader is assumed to be online, so CDN resources are fine; local file dependencies are not.

**Inline:**

- CSS in a `<style>` block. No external stylesheet files.
- Raster images (PNG, JPG) as base64 data URIs.
- Vector graphics (SVG) as `<svg>` markup, not `<img src="…svg">`.
- All chart data in `<script type="application/json">` blocks, referenced by `id`.

**CDN is allowed:**

- Google Fonts via `<link>`.
- Chart library (Plotly, Chart.js, uPlot, etc.) via its CDN URL.

**Not allowed:**

- Relative paths to images, stylesheets, data files, or any local asset.
- PDF figures — convert to SVG or PNG before embedding.
- `<iframe>` or `<embed>` pointing at local files.

## Content style

The HTML should express the case as clearly and professionally as possible. Use interactiveness to assist you in this. There is no need to be bold, catch attention, etc. Imagine that this HTML is created to convey the case as professionally and clearly as possible to a work colleague.

## Embedding conventions

For every asset and data block embedded in the document, follow these rules:

- **Raster images (PNG, JPG, GIF, WebP)** → base64 data URI in `<img>`.
- **SVG** → inline `<svg>` markup with `id` attributes prefixed (e.g. `fig3-gradient`) to prevent collisions between multiple SVGs in the same document. Rewrite `href="#…"`, `xlink:href="#…"`, and `url(#…)` references to match the prefixed ids.
- **Tabular data (CSV, TSV)** → column-major JSON (`{"x": [...], "y": [...]}`) wrapped in `<script type="application/json" id="…">`. Chart-rendering code reads from the element by id.
- **JSON data** → wrapped in `<script type="application/json" id="…">`, with any `</` sequences in the payload escaped as `<\/` to prevent script-tag breakout.

The conventions are the rule. `scripts/inline.py` is a reference implementation showing correct handling of each case — use it directly, copy parts of it, or write embedding inline, whichever fits the data shape.

## Files in this skill

- `design-system.md` — the visual design system: colors, typography, spacing, components (figures, data tables, dark sections, status chips, etc.). This is authoritative. Read it before writing any CSS, and don't improvise on tokens, radii, or component anatomy. Build the CSS fresh from these tokens rather than copying a previous report's CSS verbatim — drift is the failure mode this skill exists to prevent.
- `scripts/inline.py` — reference implementation for asset and data embedding. See *Embedding conventions* above.
