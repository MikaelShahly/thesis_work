# Packages

## The baseline set (loaded by `assets/preamble.tex`)

Everything the templates use lives in `preamble.tex` and comes from the
TeX Live sets the user installs (`texlive-latex-recommended`, `-latex-extra`,
`-fonts-recommended`, `-science`). Stay within it.

| Package | Purpose |
|---|---|
| `fontenc`, `inputenc`, `lmodern` | T1 encoding, UTF-8 input, scalable Computer Modern |
| `babel` (british) | hyphenation + language-aware `csquotes`/`cleveref` |
| `microtype` | spacing/justification polish (also reduces overfull boxes) |
| `amsmath`, `amssymb`, `mathtools`, `bm` | math, symbols, extensions, bold vectors |
| `siunitx` | units and numbers: `\SI{22}{\meter\per\second}`, `\num{1.5e6}`, `\ang{8}` |
| `graphicx` | `\includegraphics` — figures arrive as **PDF** (vector) |
| `float` | the `[H]` placement specifier |
| `caption`, `subcaption` | caption styling, side-by-side subfigures |
| `booktabs`, `array` | professional tables (`\toprule`/`\midrule`/`\bottomrule`) |
| `xcolor`, `csquotes` | colour, `\enquote{}` |
| `natbib` | classic BibTeX citations (`\citep`/`\citet`) |
| `hyperref` (hidelinks), `cleveref` | links + smart references (`\cref{fig:x}`) |

## If you use X, you must load Y

These cause `Undefined control sequence` (or a float error) when the package is
missing. All the ones below are already in the baseline — the table is to stop
the recovery loop chasing the wrong fix.

| If you use… | You need | Already loaded? |
|---|---|---|
| `\SI{}`, `\num{}`, `\ang{}` | `siunitx` | yes |
| `\includegraphics` | `graphicx` | yes |
| `\begin{figure}[H]` | `float` | yes |
| `\toprule`, `\midrule`, `\bottomrule` | `booktabs` | yes |
| `\begin{subfigure}` | `subcaption` | yes |
| `\cref`, `\Cref` | `cleveref` (after `hyperref`) | yes |
| `\bm{}` | `bm` | yes |
| `\coloneqq`, `\DeclarePairedDelimiter` | `mathtools` | yes |
| `\rowcolor`, `\cellcolor` | `\usepackage[table]{xcolor}` or `colortbl` | **no** — not in baseline |
| `\sout`, `\xout` | `ulem` | **no** |
| `\begin{algorithm}` | `algorithm2e` or `algorithmicx` | **no** |

## Reaching beyond the set

If a document genuinely needs a package outside the baseline (e.g. `colortbl`
for coloured table rows, an `algorithm` environment), **do not silently work
around it and do not assume `tlmgr install`** — tell the user which package is
needed and let them install it on approval. Most reports never need anything
beyond the baseline; prefer rephrasing to adding a dependency.

## Load order (already correct in the preamble)

`fontenc/inputenc/lmodern` → `babel` → math (`amsmath`…) → `siunitx` →
graphics/tables → `csquotes` → `natbib` → `hyperref` → **`cleveref` last**.
`cleveref` after `hyperref` is the one that bites if reordered.
