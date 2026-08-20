#!/usr/bin/env python3
"""
logdigest.py — distil a LaTeX .log into the one thing to fix next.

  python3 logdigest.py document.log            # first hard error + suggestion, then warnings
  python3 logdigest.py document.log --warnings-only

This drives the recovery loop: compile -> if no PDF, read the FIRST ERROR ->
fix that one construct in the .tex -> recompile -> repeat. Fixing only the
first real error each pass avoids chasing cascade errors.
"""
import sys, re


def suggest(errline):
    e = errline
    if "auto expansion" in e or ("font expansion" in e and "scalable" in e):
        return ("Non-scalable fonts: install lmodern (texlive-fonts-recommended), or "
                "load microtype with [expansion=false]. The preamble guards this already.")
    if "not found" in e and ".sty" in e:
        m = re.search(r"`([^']+)\.sty'", e)
        pkg = m.group(1) if m else "?"
        return (f"Missing package '{pkg}'. Stay within the baseline set; if it is "
                f"genuinely needed, ask the user to install it (don't work around it).")
    if "Undefined control sequence" in e:
        return ("Unknown command: check the spelling, or load the package that defines "
                "it (see references/packages.md).")
    if "Missing $ inserted" in e:
        return ("A math symbol was used in text mode. Wrap it in $...$ — note especially "
                "that < and > must be $<$ / $>$ (or \\textless/\\textgreater).")
    if "Missing \\begin{document}" in e:
        return "Stray text or a bad character in the preamble before \\begin{document}."
    if "Too many }" in e or "Extra }" in e:
        return "Unbalanced braces — find the extra } or the missing {."
    if "Environment" in e and "undefined" in e:
        return "Unknown environment — load the package that provides it."
    if "File ended while scanning" in e or "Runaway argument" in e:
        return "An unclosed brace or environment — check the construct named in the error."
    if "Undefined" in e and "citation" in e.lower():
        return "Citation key not in the .bib (or BibTeX hasn't run) — check the key."
    return "Fix the construct at the indicated source line (l.NN), then recompile."


def main():
    if len(sys.argv) < 2:
        print("usage: logdigest.py document.log [--warnings-only]"); return
    path = sys.argv[1]
    warnings_only = "--warnings-only" in sys.argv[2:]
    try:
        log = open(path, encoding="utf-8", errors="replace").read()
    except FileNotFoundError:
        print("no log file:", path); return
    lines = log.splitlines()

    if not warnings_only:
        err_re = re.compile(
            r"(^! )"                       # classic LaTeX error
            r"|(^.+?\.\w+:\d+:)"           # file:line: (from -file-line-error)
            r"|(pdfTeX error)"
            r"|(^! LaTeX Error)"
            r"|(Emergency stop)"
            r"|(Fatal error occurred)"
        )
        for i, ln in enumerate(lines):
            if err_re.search(ln):
                block = [ln]
                for j in range(i + 1, min(i + 9, len(lines))):
                    block.append(lines[j])
                    if lines[j].startswith("l.") or lines[j].strip() == "":
                        break
                print("FIRST ERROR:")
                print("\n".join(block))
                print("\nSUGGESTION:", suggest(ln))
                print()
                break
        else:
            print("No hard error line in the log.\n")

    warn = []
    if re.search(r"Citation .* undefined", log):
        warn.append("Undefined citation(s) — check .bib keys / that BibTeX ran.")
    if re.search(r"(There were undefined references|Reference .* undefined)", log):
        warn.append("Undefined reference(s) — check \\label/\\ref, or just recompile.")
    n_over = len(re.findall(r"Overfull \\hbox", log))
    if n_over:
        warn.append(f"{n_over} overfull hbox (text into margin) — rephrase or resize.")
    if re.search(r"Missing character|Font shape .* undefined", log):
        warn.append("Missing glyph/font shape — check encoding or font package.")
    if warn:
        print("WARNINGS:")
        for w in warn:
            print("  -", w)


if __name__ == "__main__":
    main()
