// Deterministic project-name → folder-name slug. Must produce the
// same output as `slugify()` in src/db.py — otherwise the frontend's
// duplicate check would disagree with the backend's UNIQUE index.
//
// Tested parity:
//   "NACA 0012 airfoil"  → "naca-0012-airfoil"
//   "Heat exchanger (v2)" → "heat-exchanger-v2"
//   "Café flow"          → "cafe-flow"
//   "!!!"                → "project"    (fallback)
const COMBINING_MARKS = /[̀-ͯ]/g;
const NON_ASCII = /[^\x00-\x7f]/g;
const NON_WORD = /[^a-z0-9_\s-]/g;
const COLLAPSE = /[\s_-]+/g;

export function slugify(name) {
  if (!name) return "project";
  let s = name
    .normalize("NFKD")
    .replace(COMBINING_MARKS, "")
    .replace(NON_ASCII, "")
    .toLowerCase()
    .replace(NON_WORD, "")
    .trim();
  s = s.replace(COLLAPSE, "-").slice(0, 60);
  return s || "project";
}
