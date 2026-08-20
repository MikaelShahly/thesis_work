---
name: latex-report
description: >
  Use this to produce a LaTeX document — typically a technical report or a
  scientific paper — as an editable .tex compiled to PDF, and to edit it as
  needed. Triggers: "LaTeX", ".tex", "compile to PDF", "PDF report/paper",
  "math-heavy" or "paper-grade" write-up with equations, figures, tables, and
  citations. This skill covers the LaTeX mechanics (a baseline preamble, two
  layout skeletons, compiling, error recovery); the document's structure and
  content are decided by the caller, not by this skill. Do NOT use for HTML. 
  Invoke without arguments.
---

# LaTeX report / paper generation

Produce a document as LaTeX, compile it to PDF, and iterate by editing the
`.tex`. The **`.tex` is the source of truth and is meant to be edited** —
editing the LaTeX and recompiling *is* the workflow; the PDF is a disposable
build output.

This is a **LaTeX mechanics** skill: it provides a fixed, clash-free preamble,
two content-free layout skeletons, a compile pipeline, and error recovery. What
sections the document has and what they say is up to the caller — this skill
does not prescribe document structure.

## Setup (user-provided)

The user installs TeX Live; this skill installs nothing. Verify first:

```bash
bash scripts/check_deps.sh
```

Baseline (Debian/Ubuntu): `texlive-latex-recommended texlive-latex-extra
texlive-fonts-recommended texlive-science latexmk`. Stay within this set; if a
document genuinely needs a package outside it, ask the user to install it rather
than working around it. See `references/packages.md`.

## Workflow

1. **Start from a skeleton** in whatever directory you're authoring the
   document — this skill does not dictate where the document lives. Keep
   `preamble.tex` (and `references.bib`, if citing) alongside the `.tex`:
   ```bash
   cp assets/preamble.tex assets/references.bib .
   cp assets/skeleton-report.tex document.tex   # or skeleton-paper.tex
   ```
2. **Write the content.** Put any figures (finished **PDF**) in a `figures/`
   subdirectory next to `document.tex` (relative include — keep it adjacent).
3. **Compile:**
   ```bash
   bash scripts/build.sh document.tex
   ```
   Runs `latexmk` (pdflatex, nonstopmode) — multi-pass with BibTeX.
4. **Review** the compiled PDF using the Read tool (figures sized right, tables
   clean, equations and cross-references resolved).
5. **Iterate / recover.** Edit the `.tex` and rebuild. On a failed build, run the
   log digest and fix the first real error (see Error recovery).
6. **Clean up when final.** The build leaves LaTeX scratch (`*.aux`, `*.log`,
   `*.fls`, `*.fdb_latexmk`) next to the `.tex`. Once the PDF is final, run
   `latexmk -c` so the folder holds only the source, `figures/`, and the PDF.

## Layout skeletons

Both use the `article` class and `\input{preamble}`; both are content-free —
they wire up the document, you supply the structure.

- **`skeleton-report.tex`** — single-column report layout: title block, body,
  commented snippets for figures/tables/equations/citations, optional bibliography.
- **`skeleton-paper.tex`** — scientific-paper layout: adds the author/affiliation
  block, abstract, and keywords; a comment shows the two-column switch.

`examples/demo.tex` is a neutral mechanics demonstration (and compile smoke
test) that exercises every feature — useful to confirm the toolchain works and
to see the pieces wired together. It is not a structure to copy.

## Authoring mechanics

- **Math** — native LaTeX (`amsmath`/`mathtools`). Label equations and reference
  with `\cref{eq:...}`. Bold vectors via `\vec{}` (mapped to `\bm`).
- **Units & numbers** — always `siunitx`: `\SI{22}{\meter\per\second}`,
  `\num{1.5e6}`, `\ang{8}`, `\SI{0.5}{\percent}`. Don't hand-type units.
- **Figures** — finished **PDF** (vector) in `figures/`, included at
  `0.75`–`0.85\textwidth` inside `\begin{figure}[H]`, with a caption and
  `\label{fig:...}`; reference with `\cref`. (pgfplots is not in the baseline;
  figures arrive as PDFs.)
- **Tables** — `booktabs` (`\toprule`/`\midrule`/`\bottomrule`, no vertical
  rules); reference with `\cref{tab:...}`.
- **Citations** — keys in `references.bib`; `\citep{}`/`\citet{}`;
  `\bibliographystyle{plainnat}`. latexmk runs BibTeX automatically.
- **Escaping** — escape `% & _ # $`; write `<`/`>` as `$<$`/`$>$` or
  `\textless`/`\textgreater` (a bare `<`/`>` silently prints garbage under T1).

## Compilation

`scripts/build.sh document.tex` uses `latexmk -pdf` with
`pdflatex -interaction=nonstopmode` — **nonstopmode, not `-halt-on-error`** — so
a PDF still emerges through first-pass warnings that resolve on later passes.
latexmk decides the pass count and runs BibTeX when a `\bibliography` is present.

## Error recovery

After every build: no PDF → `python3 scripts/logdigest.py document.log`, fix the
**first** real error only, recompile (repeat; usually converges in 1–2 rounds).
PDF produced → still check the digest's warnings and the preview, since some
problems compile cleanly and only show in the output. Full guidance and the
silent-failure list: `references/error-recovery.md`.

## Typesetting hygiene

Figures at 0.75–0.85`\textwidth` (full width looks crude and overflows);
`\begin{figure}[H]` to keep a float where it's written; use
`\newpage`/`\clearpage` sparingly; reference floats with `\cref`, never a
hard-coded number.

## Pre-delivery checklist

- [ ] Builds cleanly; digest shows no first error and no undefined
      citations/references
- [ ] Equations typeset and `\cref`-referenced
- [ ] Figures are PDF, sized 0.75–0.85\textwidth, captioned and referenced
- [ ] Units/numbers via siunitx; no bare `<`/`>` in text
- [ ] Tables use booktabs and don't overflow the margin
- [ ] Bibliography renders; all `\cite` keys resolve
- [ ] PDF reviewed with Read tool
