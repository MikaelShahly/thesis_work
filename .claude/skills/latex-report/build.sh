#!/usr/bin/env bash
#
# build.sh — compile a LaTeX report/paper to PDF.
#
#   bash scripts/build.sh document.tex
#
# Uses latexmk with the pdflatex engine in nonstopmode (NOT -halt-on-error),
# so a PDF still emerges through first-pass warnings that resolve on later
# passes. latexmk handles the multi-pass and runs BibTeX automatically when a
# \bibliography is present.
#
# On failure (no PDF), the first real error from the .log is printed via
# logdigest.py — that is the input to the fix-and-recompile recovery loop.
# Nothing is auto-installed; run scripts/check_deps.sh if tools are missing.
set -uo pipefail   # deliberately NOT -e: we handle latexmk's exit code ourselves

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEX="${1:?usage: build.sh document.tex}"
[[ -f "$TEX" ]] || { echo "not found: $TEX" >&2; exit 1; }
TEX="$(realpath "$TEX")"
DIR="$(dirname "$TEX")"; BASE="$(basename "$TEX" .tex)"

# --- runtime check (no auto-install) ---
for b in latexmk pdflatex bibtex; do
  command -v "$b" >/dev/null 2>&1 || {
    echo "Missing '$b'. Run scripts/check_deps.sh and install TeX Live (see SKILL.md)." >&2
    echo "Not auto-installing." >&2; exit 1; }
done

cd "$DIR"

echo "[1/2] latexmk -> pdf (pdflatex, nonstopmode)"
latexmk -pdf -bibtex \
  -pdflatex='pdflatex -interaction=nonstopmode -file-line-error %O %S' \
  "$BASE.tex"
RC=$?

if [[ ! -f "$BASE.pdf" ]]; then
  echo "compile FAILED — no PDF produced. First error:" >&2
  python3 "$SCRIPT_DIR/logdigest.py" "$BASE.log" >&2 || true
  exit 1
fi
[[ $RC -ne 0 ]] && echo "  note: latexmk reported warnings; a PDF was still produced."

echo "done: $DIR/$BASE.pdf"
# surface non-fatal issues worth a look (undefined refs/citations, overfull boxes)
python3 "$SCRIPT_DIR/logdigest.py" "$BASE.log" --warnings-only 2>/dev/null || true
