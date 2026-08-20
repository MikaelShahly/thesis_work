# Error recovery & pitfalls

## The recovery loop

Compilation uses `pdflatex -interaction=nonstopmode`, so it runs to the end and
often produces a PDF even when something is wrong. After every build:

1. **No PDF?** Run the log digest and fix the FIRST real error only:
   ```bash
   python3 scripts/logdigest.py document.log
   ```
   Fix that one construct in the `.tex`, then recompile. Fixing only the first
   error each pass avoids chasing cascade errors that disappear on their own.
2. **PDF produced?** Still check the digest's WARNINGS section (undefined
   citations/references, overfull boxes) and skim the preview PNGs — many real
   problems compile "successfully" (see silent failures below).

Typical first-error fixes: drop or swap a missing package, add the package a
command needs (see `packages.md`), wrap a stray math symbol in `$…$`, balance a
brace. Recompile after each single fix; most documents converge in 1–2 rounds.

## Silent failures (compile clean, look wrong)

The dangerous ones — no error, wrong output:

- **`<` and `>` in text mode.** Under T1 these render as inverted glyphs (¡ ¿),
  not `<`/`>`. Always use math/text commands:
  `$<$`, `$>$`, `$\leq$`, `$\geq$`, or `\textless`, `\textgreater`.
  Example: `x < 5` → `\(x < 5\)` (math) or `$<$5` in text.
- **Unescaped specials.** `% & _ # $` must be escaped: `\%  \&  \_  \#  \$`.
  A bare `%` silently comments out the rest of the line; a bare `_`/`^` in text
  errors or shifts into math.
- **Number/unit text.** Prefer `siunitx` (`\num`, `\SI`, `\ang`) over typing
  `1.5e6` or `22 m/s` directly — it formats consistently and avoids stray math.
- **Undefined `\ref`/`\cref`** shows as `??` — recompile (cross-refs need a
  second pass; `latexmk` handles this) or check the `\label`.

## Common hard errors

| Message | Cause | Fix |
|---|---|---|
| `File '<pkg>.sty' not found` | package not installed | use baseline; else ask user to install |
| `Undefined control sequence` | typo or missing package | check spelling / load the package |
| `Missing $ inserted` | math symbol in text | wrap in `$…$` (often a `<`/`>`/`_`) |
| `Missing \begin{document}` | junk in preamble | remove stray text before `\begin{document}` |
| `Runaway argument` / `File ended while scanning` | unclosed `{` or environment | close the brace/`\end{...}` |
| `Undefined citation` | bad `.bib` key / BibTeX didn't run | check key; `latexmk -bibtex` reruns it |

## Figure & layout hygiene

- Size figures at `0.75`–`0.85\textwidth` — full width looks crude and overflows.
- Use `\begin{figure}[H]` (from `float`) to keep a figure where it's written
  instead of drifting to the next page.
- Prefer prose to bullet lists in the body of a report.
- Use `\newpage`/`\clearpage` sparingly — let LaTeX break pages.
- Reference floats with `\cref{fig:...}` / `\cref{tab:...}`, never hard-coded
  "Figure 2".
