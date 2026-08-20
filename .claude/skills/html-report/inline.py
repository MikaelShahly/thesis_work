#!/usr/bin/env python3
"""
inline.py — Encode assets and data for inline embedding in HTML reports.

Usage:
    python inline.py <path> [--id ID] [--append HTML_FILE]

Dispatches on file extension:
    .png .jpg .jpeg .gif .webp  ->  base64 <img> data URI
    .svg                        ->  inlined <svg> with id namespacing
    .csv .tsv                   ->  column-major JSON in <script type="application/json">
    .json                       ->  validated JSON in <script type="application/json">
    .npy                        ->  numpy array -> JSON (requires numpy)

Output goes to stdout unless --append is given.
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"


def encode_image(path: Path) -> str:
    mime = IMAGE_MIME[path.suffix.lower()]
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f'<img src="data:{mime};base64,{data}" alt="">'


def inline_svg(path: Path, ns_id: str) -> str:
    """Inline SVG with id namespacing so multiple SVGs in one doc don't collide."""
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"<\?xml[^?]*\?>", "", text)
    text = re.sub(r"<!DOCTYPE[^>]*>", "", text).strip()

    ET.register_namespace("", SVG_NS)
    ET.register_namespace("xlink", XLINK_NS)
    root = ET.fromstring(text)

    prefix = f"{ns_id}-"
    id_map: dict[str, str] = {}
    for el in root.iter():
        old = el.get("id")
        if old:
            new = prefix + old
            id_map[old] = new
            el.set("id", new)

    if id_map:
        url_ref = re.compile(r"url\(#([^)]+)\)")
        href_attrs = ("href", f"{{{XLINK_NS}}}href")
        for el in root.iter():
            for attr in href_attrs:
                v = el.get(attr)
                if v and v.startswith("#") and v[1:] in id_map:
                    el.set(attr, "#" + id_map[v[1:]])
            for attr, v in list(el.attrib.items()):
                if "url(#" in v:
                    new_v = url_ref.sub(
                        lambda m: f"url(#{id_map.get(m.group(1), m.group(1))})", v
                    )
                    if new_v != v:
                        el.set(attr, new_v)

    return ET.tostring(root, encoding="unicode")


def csv_to_columns(path: Path, delimiter: str) -> dict:
    """Parse CSV/TSV into column-major dict; coerce numeric strings to float."""
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f, delimiter=delimiter))
    if not rows:
        return {}
    header, *body = rows
    header = [h.strip() for h in header]
    cols: dict[str, list] = {h: [] for h in header}
    for row in body:
        for h, val in zip(header, row):
            val = val.strip()
            try:
                cols[h].append(float(val))
            except ValueError:
                cols[h].append(val)
    return cols


def wrap_json(obj, element_id: str) -> str:
    payload = json.dumps(obj, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")  # prevent </script> breakout
    return f'<script type="application/json" id="{element_id}">{payload}</script>'


def encode_npy(path: Path, element_id: str) -> str:
    try:
        import numpy as np
    except ImportError:
        raise SystemExit("numpy required for .npy files (pip install numpy)")
    return wrap_json(np.load(path, allow_pickle=False).tolist(), element_id)


def derive_id(path: Path) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", path.stem) or "asset"


def dispatch(path: Path, element_id: str | None) -> str:
    ext = path.suffix.lower()
    eid = element_id or derive_id(path)
    if ext in IMAGE_MIME:
        return encode_image(path)
    if ext == ".svg":
        return inline_svg(path, eid)
    if ext == ".csv":
        return wrap_json(csv_to_columns(path, ","), eid)
    if ext == ".tsv":
        return wrap_json(csv_to_columns(path, "\t"), eid)
    if ext == ".json":
        return wrap_json(json.loads(path.read_text(encoding="utf-8")), eid)
    if ext == ".npy":
        return encode_npy(path, eid)
    raise SystemExit(f"Unsupported extension: {ext}")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("path", type=Path)
    p.add_argument("--id", dest="element_id", help="id attribute / SVG namespace prefix")
    p.add_argument(
        "--append", type=Path, help="append snippet to this file instead of stdout"
    )
    args = p.parse_args()

    if not args.path.is_file():
        raise SystemExit(f"Not found: {args.path}")

    snippet = dispatch(args.path, args.element_id)

    if args.append:
        with args.append.open("a", encoding="utf-8") as f:
            f.write(snippet + "\n")
    else:
        sys.stdout.write(snippet + "\n")


if __name__ == "__main__":
    main()
