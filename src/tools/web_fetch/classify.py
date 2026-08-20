"""Link classification + image signal words (spec §4.5.1, plan §3).

Classification order is **non-destructive** — only the four non-fetchable schemes
are dropped (return ``None``); everything else is kept and tagged. Order:
drop schemes → chrome (inside nav/header/footer/aside) → data/alternate_pdf by
**extension (before host)** → DOI/arXiv citation → same registrable domain ``nav``
else ``external``. Shared by the HTML extractor (full DOM context) and the PDF
stager (link annotations, no chrome context).
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# CFD-flavoured data-file extensions (spec §4.5.1). Reinforced corpus: grids,
# meshes, case dicts, point clouds, archives, CAD interchange.
DATA_EXTENSIONS = frozenset({
    "dat", "csv", "tsv", "txt", "nml", "inp", "cfg",
    "vtk", "vtu", "vtp", "foam", "stl", "obj", "msh", "cgns",
    "grd", "p3d", "xyz", "plt", "h5", "hdf5", "nc", "npz", "npy", "mat",
    "zip", "tar", "gz", "tgz", "stp", "step", "iges", "igs",
})

# Tokens (matched whole-token in an <img> src/class/alt/id) that mark a non-content
# image — site chrome, ads, badges. Deliberately NOT "thumb": Wikimedia serves every
# real article image via a `/thumb/` URL, so it over-dropped Wikipedia figures. Also
# avoid "profile" (collides with "velocity profile" plots) — avatars are caught by
# "avatar"/"avatars". The bias stays toward keeping real figures (the agent's vision
# is the final judge), so this only lists clearly-never-content classes.
IMAGE_SIGNAL_WORDS = frozenset({
    # site chrome / UI
    "logo", "icon", "sprite", "avatar", "avatars", "banner", "button",
    # ads / sponsorship / monetization
    "ad", "ads", "advert", "sponsor", "spon", "promo", "ebay", "deal", "deals",
    "premium", "upgrade", "affiliate",
    # badges / decorations / reactions
    "badge", "ribbon", "award", "decal", "emoji", "smilie", "smiley", "reaction",
    "license", "creativecommons",
})

_DOI_RE = re.compile(r"10\.\d{4,9}/", re.IGNORECASE)


def _ext(url: str) -> str:
    last = urlsplit(url).path.rsplit("/", 1)[-1]
    return last.rsplit(".", 1)[-1].lower() if "." in last else ""


def _registrable(host: str) -> str:
    """Cheap eTLD+1 approximation: last two labels. Good enough for the
    gov/edu/com corpus (note: wrong for multi-part TLDs like co.uk)."""
    labels = (host or "").lower().split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host.lower()


def _is_citation(url: str) -> bool:
    low = url.lower()
    return (
        "doi.org/" in low
        or "arxiv.org/abs/" in low
        or "arxiv.org/pdf/" in low
        or "/doi/" in low
        or bool(_DOI_RE.search(low))
    )


def classify_link(
    url: str,
    *,
    text: str | None = None,
    in_chrome: bool = False,
    base_host: str | None = None,
) -> tuple[str, str | None] | None:
    """Return ``(type, mime_hint)`` or ``None`` if the link should be dropped
    (non-fetchable scheme)."""
    low = url.strip().lower()
    if (
        low.startswith(("mailto:", "tel:", "javascript:", "data:"))
        or low.startswith("#")
        or not low
    ):
        return None

    if in_chrome:
        return ("chrome", None)

    ext = _ext(url)
    if ext == "pdf":
        return ("alternate_pdf", "pdf")
    if ext in DATA_EXTENSIONS:
        return ("data", ext)

    if _is_citation(url):
        return ("citation", None)

    host = urlsplit(url).hostname or ""
    if not host:
        return ("nav", None)  # relative/internal that didn't resolve to a host
    if base_host and _registrable(host) == _registrable(base_host):
        return ("nav", None)
    return ("external", None)
