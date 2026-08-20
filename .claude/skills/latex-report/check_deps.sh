#!/usr/bin/env bash
#
# check_deps.sh — verify the TeX Live toolchain and baseline packages are
# present. Installs NOTHING; reports what is missing and how to install it
# (with the user's approval). The skill stays within this fixed set.
set -uo pipefail
miss=0

echo "Binaries:"
for b in pdflatex latexmk bibtex pdftoppm kpsewhich; do
  if command -v "$b" >/dev/null 2>&1; then echo "  ok   $b"
  else echo "  MISS $b"; miss=1; fi
done

echo "LaTeX packages:"
pkgs="amsmath amssymb mathtools bm siunitx graphicx float booktabs array \
caption subcaption xcolor csquotes natbib microtype lmodern hyperref \
cleveref geometry babel"
for p in $pkgs; do
  if kpsewhich "$p.sty" >/dev/null 2>&1; then echo "  ok   $p"
  else echo "  MISS $p"; miss=1; fi
done

echo
if [[ $miss -eq 0 ]]; then
  echo "All present — toolchain ready."
else
  cat <<'EOF'
Some pieces are missing. The baseline is provided (Debian/Ubuntu) by:

  texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended \
  texlive-science latexmk

Install AFTER user approval, e.g.:
  sudo apt-get install texlive-latex-recommended texlive-latex-extra \
       texlive-fonts-recommended texlive-science latexmk

Do not reach beyond this set. If a document genuinely needs another package,
ask the user to install it rather than working around it.
EOF
fi
exit $miss
