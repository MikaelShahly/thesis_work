"""ParaView bridge: runs inside `paraview --script=bridge.py`.

Spins up an HTTP server on localhost:8765 driven by external requests.
Mutating ParaView proxies must happen on the Qt main thread, so HTTP worker
threads enqueue callables and the main thread drains the queue via a VTK
repeating timer on the active view's interactor (a QVTKInteractor under the
hood, which routes timers through Qt's event loop).
"""

import gzip
import json
import os
import queue
import re
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ParaView's --script startup shadows builtins min/max/sum with the VTK
# numpy_interface versions, which expect (array, axis). Re-bind the
# Python builtins so scalar max(1, x) calls don't get reinterpreted.
from builtins import max, min, sum  # noqa: A004

from vtkmodules.vtkCommonCore import vtkCommand

PORT = int(os.environ.get("PV_BRIDGE_PORT", "8765"))
# Base directory for resolving relative paths in load_dataset,
# save_screenshot, and export_snapshot. The agenticCFD lifecycle
# manager sets PV_PROJECT_ROOT to the active project's folder before
# spawning ParaView; without it we fall back to the launcher's cwd
# so the bridge is still usable in ad-hoc runs.
BASE_DIR = os.environ.get("PV_PROJECT_ROOT") or os.getcwd()
SNAPSHOT_DIR = os.path.join(BASE_DIR, ".paraview_snapshots")
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

_task_queue = queue.Queue()
_timer_iren = None
_timer_observer_id = None
_timer_id = None


def run_on_gui(func, timeout=120.0):
    done = threading.Event()
    box = {"value": None, "error": None}

    def wrapped():
        try:
            box["value"] = func()
        except Exception as e:
            box["error"] = (type(e).__name__, str(e), traceback.format_exc())
        finally:
            done.set()

    _task_queue.put(wrapped)
    if not done.wait(timeout):
        raise TimeoutError(f"GUI task did not complete within {timeout}s")
    if box["error"]:
        name, msg, tb = box["error"]
        raise RuntimeError(f"{name}: {msg}\n{tb}")
    return box["value"]


def _drain_queue(*_args):
    for _ in range(32):
        try:
            task = _task_queue.get_nowait()
        except queue.Empty:
            return
        try:
            task()
        except Exception:
            traceback.print_exc()


# ---------------------------------------------------------------------------
# Helpers (only called from inside run_on_gui callables)
# ---------------------------------------------------------------------------

def _find_proxy_by_id(target_id):
    from paraview.simple import GetSources
    for (_name, gid), proxy in GetSources().items():
        if gid == target_id:
            return proxy
    return None


def _find_view_by_id(target_id):
    from paraview.simple import GetViews
    for v in GetViews():
        if v.SMProxy.GetGlobalIDAsString() == target_id:
            return v
    return None


def _input_ids(proxy):
    ids = []
    try:
        inp = proxy.SMProxy.GetProperty("Input")
    except Exception:
        return ids
    if inp is None:
        return ids
    try:
        for i in range(inp.GetNumberOfProxies()):
            sub = inp.GetProxy(i)
            if sub is not None:
                ids.append(sub.GetGlobalIDAsString())
    except Exception:
        pass
    return ids


def _resolve_target_source(input_id):
    from paraview.simple import GetActiveSource, SetActiveSource
    if input_id:
        src = _find_proxy_by_id(input_id)
        if src is None:
            raise ValueError(f"no source with id {input_id}")
        SetActiveSource(src)
        return src
    src = GetActiveSource()
    if src is None:
        raise RuntimeError("no active source")
    return src


def _source_descriptor(proxy, default_name=None):
    from paraview.simple import GetSources
    gid = proxy.SMProxy.GetGlobalIDAsString()
    name = next((n for (n, g) in GetSources().keys() if g == gid), default_name)
    return {
        "id": gid,
        "name": name,
        "type": proxy.SMProxy.GetXMLName(),
    }


def _show_and_hide_input(new_proxy, input_proxy):
    from paraview.simple import Show, Hide, GetActiveView, Render
    view = GetActiveView()
    Show(new_proxy, view)
    Hide(input_proxy, view)
    Render()


def _hide_unused_scalar_bars():
    """Hide color legends no longer used by a visible representation in the
    active view. ParaView leaves scalar bars on until explicitly hidden, so
    without this they pile up on every recolor and orphan themselves across
    source delete/reload (verified on PV 5.13.3)."""
    from paraview.simple import GetActiveView, HideUnusedScalarBars
    view = GetActiveView()
    if view is not None:
        HideUnusedScalarBars(view)


def _collect_visible_and_ancestor_ids(view):
    from paraview.simple import GetSources, GetDisplayProperties
    keep = set()

    def walk(proxy):
        gid = proxy.SMProxy.GetGlobalIDAsString()
        if gid in keep:
            return
        keep.add(gid)
        try:
            inp = proxy.Input
        except Exception:
            return
        if inp is None:
            return
        inputs = inp if isinstance(inp, (list, tuple)) else [inp]
        for ip in inputs:
            if ip is not None:
                walk(ip)

    for (_name, _gid), proxy in GetSources().items():
        try:
            rep = GetDisplayProperties(proxy, view=view)
            if rep is not None and bool(int(rep.Visibility)):
                walk(proxy)
        except Exception:
            continue
    return keep


def _array_info_at(field_info, i):
    """Return per-array info from either a vtkPVDataSetAttributesInformation
    (uses GetArrayInformation) or a paraview.servermanager.FieldDataInformation
    wrapper (uses GetArray)."""
    if hasattr(field_info, "GetArrayInformation"):
        return field_info.GetArrayInformation(i)
    if hasattr(field_info, "GetArray"):
        return field_info.GetArray(i)
    return None


def _detect_association(src, array_name):
    def _scan(getter, label):
        try:
            info = getter()
            n = info.GetNumberOfArrays()
        except Exception:
            return None, []
        names = []
        for i in range(n):
            try:
                ai = _array_info_at(info, i)
                if ai is not None:
                    nm = ai.GetName()
                    names.append(nm)
                    if nm == array_name:
                        return label, names
            except Exception:
                continue
        return None, names

    hit, point_names = _scan(src.GetPointDataInformation, "POINTS")
    if hit:
        return "POINTS"
    hit, cell_names = _scan(src.GetCellDataInformation, "CELLS")
    if hit:
        return "CELLS"
    raise ValueError(
        f"array {array_name!r} not found; point arrays: {point_names}, "
        f"cell arrays: {cell_names}"
    )


def _check_finite(values, label):
    """Reject NaN/inf in a numeric sequence and return the float list."""
    import math
    out = []
    for v in values:
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{label}: non-numeric value {v!r}")
        if not math.isfinite(f):
            raise ValueError(f"{label}: non-finite value {v!r}")
        out.append(f)
    return out


def _check_vec3(values, label, nonzero=False):
    vec = _check_finite(values, label)
    if len(vec) != 3:
        raise ValueError(f"{label}: expected 3 floats, got {len(vec)}")
    if nonzero and (vec[0] * vec[0] + vec[1] * vec[1] + vec[2] * vec[2]) == 0.0:
        raise ValueError(f"{label}: zero-length vector not allowed")
    return vec


def _serialize_value(v):
    if hasattr(v, "SMProxy"):
        return _dump_props(v)
    if hasattr(v, "__iter__") and not isinstance(v, str):
        return list(v)
    return v


def _dump_props(proxy):
    out = {}
    for name in proxy.ListProperties():
        p = proxy.GetProperty(name)
        try:
            if p.GetPanelVisibility() != "default":
                continue
        except Exception:
            continue
        if name == "Input":
            continue
        if type(p).__name__ in ("Property", "InputProperty"):
            continue
        try:
            sm_prop = getattr(p, "SMProperty", None)
            # Proxy-list domain (SliceType, ClipType, GlyphType, SeedType, ...)
            # must be checked before Available — these properties also expose
            # Available, but it holds sub-proxy types, not enumeration strings.
            proxy_list_domain = (
                sm_prop.FindDomain("vtkSMProxyListDomain") if sm_prop is not None else None
            )
            if proxy_list_domain is not None:
                active = proxy.GetPropertyValue(name)
                active_sm = (
                    getattr(active, "SMProxy", active) if active is not None else None
                )
                entry = {
                    "type": active_sm.GetXMLName() if active_sm is not None else None,
                    "available_types": [
                        proxy_list_domain.GetProxy(i).GetXMLName()
                        for i in range(proxy_list_domain.GetNumberOfProxies())
                    ],
                }
                if active is not None:
                    entry.update(_dump_props(active))
                out[name] = entry
            elif hasattr(p, "Available"):
                enabled = list(proxy.GetPropertyValue(name) or [])
                available = list(p.Available)
                out[name] = {"enabled": enabled, "available": available}
            else:
                v = _serialize_value(proxy.GetPropertyValue(name))
                if isinstance(v, (str, int, float, bool, list, dict, type(None))):
                    out[name] = v
                else:
                    out[name] = repr(v)
        except Exception as e:
            out[name] = f"<error: {type(e).__name__}: {e}>"
    return out


def _enum_str(proxy, name):
    try:
        v = proxy.GetPropertyValue(name)
    except Exception:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)):
        return v[0] if v else None
    if hasattr(v, "__iter__"):
        try:
            lst = list(v)
            return lst[0] if lst else None
        except Exception:
            return None
    return str(v) if v is not None else None


def _color_by_summary(rep):
    try:
        car = rep.GetPropertyValue("ColorArrayName")
        if car is not None and len(car) >= 2 and car[1]:
            return {"mode": "array", "association": car[0], "array": car[1]}
    except Exception:
        pass
    return {"mode": "solid"}


def _dump_display(proxy, view):
    from paraview.simple import GetDisplayProperties
    try:
        rep = GetDisplayProperties(proxy, view=view)
    except Exception:
        rep = None
    if rep is None:
        return {"visible": False}

    rep_type = _enum_str(rep, "Representation")
    out = {
        "visible": bool(int(rep.Visibility)),
        "representation": rep_type,
        "opacity": float(rep.Opacity),
        "color_by": _color_by_summary(rep),
    }

    def _safe(getter):
        try:
            return getter()
        except Exception:
            return None

    if rep_type == "Surface":
        out["surface_color_rgb"] = _safe(lambda: list(rep.DiffuseColor))
    elif rep_type == "Surface With Edges":
        out["surface_color_rgb"] = _safe(lambda: list(rep.DiffuseColor))
        out["edge_color_rgb"] = _safe(lambda: list(rep.EdgeColor))
    elif rep_type == "Wireframe":
        out["line_color_rgb"] = _safe(lambda: list(rep.DiffuseColor))
        out["line_width"] = _safe(lambda: float(rep.LineWidth))
    elif rep_type == "Points":
        out["point_color_rgb"] = _safe(lambda: list(rep.DiffuseColor))
        out["point_size"] = _safe(lambda: float(rep.PointSize))
    elif rep_type == "Point Gaussian":
        out["point_color_rgb"] = _safe(lambda: list(rep.DiffuseColor))
        out["gaussian_radius"] = _safe(lambda: float(rep.GaussianRadius))
        out["shader_preset"] = _enum_str(rep, "ShaderPreset")
    elif rep_type == "Volume":
        out["scalar_opacity_unit_distance"] = _safe(lambda: float(rep.ScalarOpacityUnitDistance))
    elif rep_type == "Outline":
        out["outline_color_rgb"] = _safe(lambda: list(rep.DiffuseColor))

    return out


# ---------------------------------------------------------------------------
# Multiblock walking
# ---------------------------------------------------------------------------

_COMPOSITE_TYPES = (
    "vtkMultiBlockDataSet",
    "vtkPartitionedDataSet",
    "vtkPartitionedDataSetCollection",
    "vtkMultiPieceDataSet",
    "vtkUniformGridAMR",
    "vtkOverlappingAMR",
    "vtkNonOverlappingAMR",
)


def _is_composite(data):
    if data is None:
        return False
    return data.GetClassName() in _COMPOSITE_TYPES


def _walk_multiblock(data, prefix=""):
    if data is None:
        return
    if _is_composite(data):
        try:
            n = data.GetNumberOfBlocks()
        except Exception:
            return
        for i in range(n):
            child = data.GetBlock(i)
            try:
                meta = data.GetMetaData(i)
                name = meta.Get(meta.NAME()) if meta else f"block_{i}"
            except Exception:
                name = f"block_{i}"
            full = f"{prefix}/{name}" if prefix else name
            yield from _walk_multiblock(child, full)
    else:
        yield prefix, data


def _blocks_touched_from_data(data):
    out = []
    for name, leaf in _walk_multiblock(data):
        try:
            n_cells = leaf.GetNumberOfCells()
        except Exception:
            continue
        if n_cells > 0:
            b = list(leaf.GetBounds())
            out.append({
                "name": name,
                "cell_count": n_cells,
                "bbox": [[b[0], b[2], b[4]], [b[1], b[3], b[5]]],
            })
    return out


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def _resolve_selection_method(sel_sm):
    xml = sel_sm.GetXMLName()
    if xml != "AppendSelections":
        return xml.replace("SelectionSource", "").upper()
    inp = sel_sm.GetProperty("Input")
    n = inp.GetNumberOfProxies()
    if n == 0:
        return "EMPTY"
    methods = [
        inp.GetProxy(i).GetXMLName().replace("SelectionSource", "").upper()
        for i in range(n)
    ]
    return methods[0] if n == 1 else "+".join(methods)


def _resolve_selection_field(sel_sm):
    target = sel_sm
    if sel_sm.GetXMLName() == "AppendSelections":
        inp = sel_sm.GetProperty("Input")
        if inp.GetNumberOfProxies() == 0:
            return None
        target = inp.GetProxy(0)
    fp = target.GetProperty("FieldType")
    if fp is None:
        return None
    return "CELL" if fp.GetElement(0) == 0 else "POINT"


def _find_selected_source():
    from paraview.simple import GetSources
    for p in GetSources().values():
        if p.SMProxy.GetSelectionInput(0) is not None:
            return p
    return None


def get_selection_info(stats=False, array=None):
    from paraview.simple import (
        ExtractSelection, Delete, GetDisplayProperties, GetActiveView,
    )
    from paraview import servermanager
    selected_src = _find_selected_source()
    if selected_src is None:
        return {"active": False}

    sel_sm = selected_src.SMProxy.GetSelectionInput(0)
    method = _resolve_selection_method(sel_sm)
    field = _resolve_selection_field(sel_sm)

    color = None
    try:
        rep = GetDisplayProperties(selected_src, view=GetActiveView())
        color = list(rep.GetPropertyValue("SelectionColor"))
    except Exception:
        pass

    ext = ExtractSelection(Input=selected_src)
    try:
        ext.UpdatePipeline()
        info = ext.GetDataInformation()
        b = list(info.GetBounds())
        bbox = [[b[0], b[2], b[4]], [b[1], b[3], b[5]]]
        n_cells = info.GetNumberOfCells()
        n_points = info.GetNumberOfPoints()
        count = n_cells if field == "CELL" else n_points

        ranges = {}
        for assoc, getter in (
            ("point", info.GetPointDataInformation),
            ("cell", info.GetCellDataInformation),
        ):
            di = getter()
            for i in range(di.GetNumberOfArrays()):
                ai = di.GetArrayInformation(i)
                aname = ai.GetName()
                if array is not None and aname != array:
                    continue
                ncomp = ai.GetNumberOfComponents()
                try:
                    if ncomp == 1:
                        ranges[aname] = {"assoc": assoc, "range": list(ai.GetComponentRange(0))}
                    else:
                        ranges[aname] = {
                            "assoc": assoc,
                            "components": ncomp,
                            "magnitude_range": list(ai.GetComponentRange(-1)),
                        }
                except Exception:
                    pass

        blocks = []
        try:
            data = servermanager.Fetch(ext)
            try:
                blocks = _blocks_touched_from_data(data)
            finally:
                del data
        except Exception:
            pass

        result = {
            "active": True,
            "field": field,
            "method": method,
            "count": count,
            "color_rgb": color,
            "bbox": bbox,
            "blocks_touched": blocks,
            "array_ranges": ranges,
        }

        if stats:
            stats_out = _selection_stats(ext, array, field)
            result["stats"] = stats_out

        return result
    finally:
        try:
            Delete(ext)
        except Exception:
            pass


def _integrate_via_datainfo(proxy):
    """Volume/area-weighted integral of every field on `proxy`, read crash-safe.

    Runs IntegrateVariables (ParaView-side) and reads its single-element output
    through DataInformation component ranges (for one element, range == value)
    rather than servermanager.Fetch + GetTuple. The pipeline data is intact
    ParaView-side even on the OpenFOAM datasets whose *fetched* arrays come back
    corrupt, so this never touches the bad memory. Returns
    ({(assoc, name): integral}, measure) — keyed by association so callers can
    pick the cell vs point integral that matches their field — where measure is
    the integrated Volume (3D) / Area (2D), or None.
    """
    from paraview.simple import (
        IntegrateVariables, Delete, GetActiveSource, SetActiveSource,
    )
    prev_active = GetActiveSource()
    iv = IntegrateVariables(Input=proxy)
    try:
        iv.UpdatePipeline()
        integrals = {}
        measure = None
        for assoc, getter in (
            ("point", iv.GetPointDataInformation),
            ("cell", iv.GetCellDataInformation),
        ):
            di = getter()
            for i in range(di.GetNumberOfArrays()):
                ai = di.GetArray(i)
                if ai is None:
                    continue
                name = ai.GetName()
                ncomp = ai.GetNumberOfComponents()
                if ncomp == 1:
                    val = ai.GetComponentRange(0)[0]
                else:
                    val = [ai.GetComponentRange(c)[0] for c in range(ncomp)]
                if name.lower() in ("volume", "area"):
                    measure = val if ncomp == 1 else val[0]
                integrals[(assoc, name)] = val
        return integrals, measure
    finally:
        try:
            Delete(iv)
        except Exception:
            pass
        if prev_active is not None:
            try:
                SetActiveSource(prev_active)
            except Exception:
                pass


def _selection_stats(ext_proxy, only_array=None, field=None):
    """min/max/mean over each array on the selection, computed crash-safe.

    min/max come from DataInformation; mean is the volume/area-weighted average
    (field integral / measure) via _integrate_via_datainfo. Both are
    ParaView-side reads, so unlike the old Fetch + vtk_to_numpy this never
    segfaults on corrupt OpenFOAM arrays and the names stay correct (the
    fetched copies came back collapsed to their VTK type name, e.g. "float").
    std needs raw per-element access and is omitted; the mean is volume-weighted
    rather than the previous arithmetic per-cell mean.

    `field` ("CELL"/"POINT") is the selection's own association; it is reported
    first so it wins the per-name dedup — a CELL selection yields cell stats
    matching array_ranges, not the point-interpolated values.
    """
    out = {}
    info = ext_proxy.GetDataInformation()
    integrals, measure = _integrate_via_datainfo(ext_proxy)
    order = (
        ("cell", info.GetCellDataInformation),
        ("point", info.GetPointDataInformation),
    )
    if field == "POINT":
        order = order[::-1]
    for assoc, getter in order:
        di = getter()
        for i in range(di.GetNumberOfArrays()):
            ai = di.GetArrayInformation(i)
            if ai is None:
                continue
            name = ai.GetName()
            if only_array is not None and name != only_array:
                continue
            if name in out:
                continue
            ncomp = ai.GetNumberOfComponents()
            entry = {
                "assoc": assoc,
                "count": (info.GetNumberOfCells() if assoc == "cell"
                          else info.GetNumberOfPoints()),
            }
            if ncomp == 1:
                rng = ai.GetComponentRange(0)
                entry["min"], entry["max"] = rng[0], rng[1]
            else:
                entry["components"] = ncomp
                mrng = ai.GetComponentRange(-1)
                entry["magnitude_min"], entry["magnitude_max"] = mrng[0], mrng[1]
            ival = integrals.get((assoc, name))
            if measure and ival is not None:
                entry["mean"] = (ival / measure if ncomp == 1
                                 else [c / measure for c in ival])
            out[name] = entry
    return out


def create_selection(bbox=None, blocks=None, field="cell", input_id=None,
                     threshold_array=None, threshold_range=None,
                     threshold_component=None):
    """Programmatic selection creation is not supported in this build.

    Several selection-creation paths were tested against PV 5.13 + OpenFOAM:

    - SelectCells/SelectPoints query strings (e.g. "U > 5") — crash
    - ThresholdSelectionSource via proxy properties — crash
    - FrustumSelectionSource via proxy properties — works in isolated exec
      tests but crashes when invoked via the bridge's HTTP path

    The agent should:

    - Use apply_threshold_filter to subset cells by array value (branches
      the pipeline; no selection involved, no crash).
    - Use apply_clip_filter (Box) for spatial subsetting.
    - Use extract_block when the goal is "this multiblock leaf only".
    - Read selections the user makes interactively (drag-select, click-pick,
      Find Data) via get_selection_info / extract_selection — these work
      because the GUI sets the selection synchronously inside ParaView.
    """
    raise NotImplementedError(
        "create_selection is not supported in this PV 5.13 + bridge build. "
        "Use apply_threshold_filter / apply_clip_filter / extract_block to "
        "subset by value, geometry, or block. Read user-made GUI selections "
        "via get_selection_info."
    )


def clear_selection(input_id=None):
    from paraview.simple import ClearSelection, Render
    src = _resolve_target_source(input_id)
    try:
        ClearSelection(src)
    except TypeError:
        # Older API — falls back to setting selection to None.
        src.SMProxy.SetSelectionInput(0, None, 0)
    Render()
    return {"id": src.SMProxy.GetGlobalIDAsString(), "cleared": True}


# ---------------------------------------------------------------------------
# Pipeline / source listing
# ---------------------------------------------------------------------------

def list_pipeline(include_properties=False, include_display=False):
    from paraview.simple import (
        GetSources, GetDisplayProperties, GetActiveView, GetActiveSource,
    )
    view = GetActiveView()
    active = GetActiveSource()
    active_gid = active.SMProxy.GetGlobalIDAsString() if active is not None else None
    out = []
    for (name, gid), proxy in GetSources().items():
        try:
            rep = GetDisplayProperties(proxy, view=view)
            visible = bool(int(rep.Visibility)) if rep is not None else False
        except Exception:
            visible = False
        entry = {
            "id": gid,
            "name": name,
            "type": proxy.SMProxy.GetXMLName(),
            "input_ids": _input_ids(proxy),
            "visible": visible,
            "active": gid == active_gid,
        }
        if include_properties:
            entry["properties"] = _dump_props(proxy)
        if include_display:
            entry["display"] = _dump_display(proxy, view)
        out.append(entry)
    return out


def get_pipeline():
    return list_pipeline()


def get_source_info(input_id=None):
    from paraview.simple import GetActiveSource, GetActiveView, GetSources
    src = _find_proxy_by_id(input_id) if input_id else GetActiveSource()
    if src is None:
        raise RuntimeError("no source")

    gid = src.SMProxy.GetGlobalIDAsString()
    name = next((n for (n, g), _ in GetSources().items() if g == gid), None)

    di = src.GetDataInformation()
    bounds = list(di.GetBounds())
    cx = (bounds[0] + bounds[1]) / 2
    cy = (bounds[2] + bounds[3]) / 2
    cz = (bounds[4] + bounds[5]) / 2

    def _arrays(info):
        out = []
        try:
            n_arrays = info.GetNumberOfArrays()
        except Exception:
            return out
        for i in range(n_arrays):
            try:
                ai = _array_info_at(info, i)
                if ai is None:
                    continue
                rng = list(ai.GetComponentRange(-1))
            except Exception:
                continue
            out.append({
                "name": ai.GetName(),
                "components": ai.GetNumberOfComponents(),
                "range": rng,
            })
        return out

    point_arrays = _arrays(src.GetPointDataInformation())
    cell_arrays = _arrays(src.GetCellDataInformation())
    out = {
        "id": gid,
        "name": name,
        "type": src.SMProxy.GetXMLName(),
        "num_points": di.GetNumberOfPoints(),
        "num_cells": di.GetNumberOfCells(),
        "bounds": bounds,
        "center": [cx, cy, cz],
        "memory_kb": di.GetMemorySize(),
        "point_arrays": point_arrays,
        "cell_arrays": cell_arrays,
        "properties": _dump_props(src),
        "display": _dump_display(src, GetActiveView()),
    }
    # No fields, but an OpenFOAM reader skipping the 0/ dir — most likely
    # checkMesh quality fields written into 0/ that the reader is hiding.
    if not point_arrays and not cell_arrays:
        try:
            skipping = src.GetProperty("SkipZeroTime") is not None and \
                int(src.GetPropertyValue("SkipZeroTime")) == 1
        except Exception:
            skipping = False
        if skipping:
            out["hint"] = (
                "no fields loaded; if you wrote checkMesh fields to time 0, "
                "the reader skips zero time by default — call set_read_zero_time "
                "with enable=true to read them"
            )
    return out


def get_workspace():
    from paraview.simple import (
        GetViews, GetLayouts, GetActiveView, GetActiveSource,
    )
    active_view = GetActiveView()
    active_source = GetActiveSource()

    views = []
    for v in GetViews():
        try:
            vw, vh = list(v.ViewSize)
        except Exception:
            vw = vh = None
        views.append({
            "id": v.SMProxy.GetGlobalIDAsString(),
            "type": v.SMProxy.GetXMLName(),
            "view_size": [vw, vh],
        })

    layouts = []
    try:
        for layout in GetLayouts().values():
            sm = layout.SMProxy
            # Walk the layout's view assignments.
            view_ids = []
            try:
                n = sm.GetNumberOfItems() if hasattr(sm, "GetNumberOfItems") else 0
            except Exception:
                n = 0
            for i in range(n):
                try:
                    v = sm.GetView(i)
                except Exception:
                    v = None
                if v is not None:
                    view_ids.append(v.GetGlobalIDAsString())
            layouts.append({
                "id": sm.GetGlobalIDAsString(),
                "name": layout.SMProxy.GetXMLLabel() or "Layout",
                "view_ids": view_ids,
            })
    except Exception:
        pass

    sel_summary = {"active": False}
    sel_src = _find_selected_source()
    if sel_src is not None:
        sel_sm = sel_src.SMProxy.GetSelectionInput(0)
        sel_summary = {
            "active": True,
            "field": _resolve_selection_field(sel_sm),
            "method": _resolve_selection_method(sel_sm),
        }

    return {
        "active_view_id": active_view.SMProxy.GetGlobalIDAsString() if active_view else None,
        "active_layout_id": layouts[0]["id"] if layouts else None,
        "active_source_id": active_source.SMProxy.GetGlobalIDAsString() if active_source else None,
        "views": views,
        "layouts": layouts,
        "selection": sel_summary,
    }


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def get_time():
    from paraview.simple import GetActiveView, GetAnimationScene
    view = GetActiveView()
    scene = GetAnimationScene()
    available = []
    try:
        tk = scene.TimeKeeper
        timesteps = list(tk.TimestepValues) if tk and tk.TimestepValues else []
        available = [float(t) for t in timesteps]
    except Exception:
        pass
    current = None
    try:
        if view is not None:
            current = float(view.ViewTime)
    except Exception:
        pass
    return {
        "current": current,
        "available": available,
        "step_count": len(available),
    }


def set_time(t=None, step=None, move=None):
    from paraview.simple import (
        GetActiveView, GetAnimationScene, Render,
    )
    view = GetActiveView()
    scene = GetAnimationScene()
    available = []
    try:
        timesteps = list(scene.TimeKeeper.TimestepValues) or []
        available = [float(x) for x in timesteps]
    except Exception:
        pass
    if not available:
        raise RuntimeError("no timesteps available")

    target = None
    if t is not None:
        tf = float(t)
        if tf < available[0] or tf > available[-1]:
            raise ValueError(
                f"t={tf} outside available range [{available[0]}, {available[-1]}]"
            )
        # Snap to nearest available within range.
        target = min(available, key=lambda x: abs(x - tf))
    elif step is not None:
        if step < 0 or step >= len(available):
            raise ValueError(f"step {step} out of range [0, {len(available)})")
        target = available[int(step)]
    elif move is not None:
        cur = float(view.ViewTime) if view else available[0]
        idx = min(range(len(available)), key=lambda i: abs(available[i] - cur))
        if move == "next":
            idx = min(idx + 1, len(available) - 1)
        elif move == "prev":
            idx = max(idx - 1, 0)
        elif move == "first":
            idx = 0
        elif move == "last":
            idx = len(available) - 1
        else:
            raise ValueError(f"unknown move: {move}")
        target = available[idx]
    else:
        raise ValueError("set_time needs one of: t, step, move")

    if view is not None:
        view.ViewTime = target
    scene.AnimationTime = target
    Render()
    return {"current": target, "step_count": len(available)}


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------

def get_camera():
    from paraview.simple import GetActiveView
    view = GetActiveView()
    if view is None:
        raise RuntimeError("no active view")
    cam_obj = view.GetActiveCamera() if hasattr(view, "GetActiveCamera") else None
    clipping = None
    if cam_obj is not None:
        try:
            clipping = list(cam_obj.GetClippingRange())
        except Exception:
            clipping = None
    return {
        "position": list(view.CameraPosition),
        "focal": list(view.CameraFocalPoint),
        "up": list(view.CameraViewUp),
        "view_angle": float(view.CameraViewAngle),
        "parallel_projection": bool(int(view.CameraParallelProjection)),
        "parallel_scale": float(view.CameraParallelScale),
        "clipping_range": clipping,
        "view_size": list(view.ViewSize),
    }


def _block_path_in(hierarchy, name):
    """Resolve a block/patch name to its data-assembly selector path.

    Matches on the leaf name (last path segment), so 'inlet' and 'patch/inlet'
    both resolve to the same node (e.g. '/Root/boundary/inlet'). Returns None if
    the hierarchy is absent or the name is not present in the loaded data.
    """
    if hierarchy is None:
        return None
    nid = hierarchy.FindFirstNodeWithName(name.split("/")[-1])
    return hierarchy.GetNodePath(nid) if nid >= 0 else None


def _meshregion_selector(src, name):
    """Return the MeshRegions selector matching `name` (full name or leaf), or
    None. Lets callers tell a known-but-unloaded patch apart from a genuinely
    unknown name, so the error can name the exact set_openfoam_patches call."""
    p = src.GetProperty("MeshRegions")
    if p is None:
        return None
    leaf = name.split("/")[-1]
    return next(
        (a for a in p.Available if a == name or a.split("/")[-1] == leaf),
        None,
    )


def _available_block_names(src):
    """Best-effort patch/block names for an error hint. Prefers the OpenFOAM
    reader's MeshRegions (includes unloaded patches); returns None otherwise."""
    p = src.GetProperty("MeshRegions")
    if p is not None:
        try:
            return list(p.Available)
        except Exception:
            pass
    return None


def _block_bounds(src, patches):
    """Server-side union bounds of one or more multiblock leaves (OpenFOAM patches).

    ``patches`` is a patch name or list of names. Each matches on the leaf name
    (last path segment), so callers pass the names as reported by
    ``get_openfoam_patches`` ('inlet' or 'patch/inlet'). Resolves each block via
    the data-assembly hierarchy and reads the combined bounds through a single
    throwaway ``ExtractBlock`` — authoritative across MPI ranks, unlike a
    client-side ``Fetch`` which does not bring patch geometry over.
    """
    from paraview.simple import ExtractBlock, Delete, GetActiveSource, SetActiveSource
    if isinstance(patches, str):
        patches = [patches]
    if not patches:
        raise ValueError("no patch given to frame")
    src.UpdatePipeline()
    hierarchy = src.GetDataInformation().GetHierarchy()
    paths = []
    for name in patches:
        path = _block_path_in(hierarchy, name)
        if path is None:
            # set_camera is a view op; it does not load data. Distinguish a
            # known-but-unloaded patch (one-step fix) from an unknown name.
            selector = _meshregion_selector(src, name)
            if selector is not None:
                raise ValueError(
                    f"patch {name!r} exists but is not loaded — call "
                    f"set_openfoam_patches(enable=[{selector!r}]) first, "
                    f"then frame it"
                )
            avail = _available_block_names(src)
            listing = f" available: {avail};" if avail else ""
            raise ValueError(
                f"no patch named {name!r};{listing} pass a name as reported by "
                f"get_openfoam_patches (full 'patch/walls' or leaf 'walls')"
            )
        paths.append(path)
    prev = GetActiveSource()
    eb = ExtractBlock(Input=src)
    try:
        eb.Selectors = paths
        eb.UpdatePipeline()
        b = eb.GetDataInformation().GetBounds()
    finally:
        SetActiveSource(prev)
        Delete(eb)
    if b is None or len(b) != 6 or b[0] > b[1]:
        raise ValueError(
            f"blocks {patches!r} have no geometry — load them with "
            f"set_openfoam_patches before framing"
        )
    return list(b)


def _fit_camera(view, source_id, bounds=None):
    """Reset camera to fit explicit ``bounds``, a specific source's bounds
    (``source_id``), or all visible data (both None).

    Uses ``vtkPVRenderView::ResetCameraScreenSpace`` — matches the GUI's "Zoom
    Closest to Data" button. Tighter than the diagonal-based ``ResetCamera`` for
    elongated/planar sources; equivalent for cubic ones.
    """
    pvview = view.GetClientSideView()
    if bounds is not None:
        pvview.ResetCameraScreenSpace(list(bounds))
        return
    if source_id is None:
        pvview.ResetCameraScreenSpace()
        return
    src = _find_proxy_by_id(source_id)
    if src is None:
        raise ValueError(f"no source with id {source_id}")
    b = src.GetDataInformation().GetBounds()
    if b is None or len(b) != 6 or b[0] > b[1]:
        raise RuntimeError(f"source {source_id} has no valid bounds")
    pvview.ResetCameraScreenSpace(list(b))


def set_camera(preset=None, toward=None, position=None, focal=None, up=None,
               zoom=None, dolly=None, azimuth=None, elevation=None, roll=None,
               parallel=None, parallel_scale=None, id=None, patch=None):
    from paraview.simple import GetActiveView, Render
    view = GetActiveView()
    if view is None:
        raise RuntimeError("no active view")

    if preset is not None and toward is not None:
        raise ValueError("--preset and --toward are mutually exclusive")

    # `patch` frames a single multiblock leaf instead of a whole source. `id`
    # (if given) selects which source to look in; otherwise the OpenFOAM reader.
    patch_bounds = None
    if patch is not None:
        patch_bounds = _block_bounds(_openfoam_reader_for(id), patch)

    # Reset stale FOV from prior --zoom calls so auto-fit math doesn't collapse.
    if preset is not None or toward is not None:
        view.CameraViewAngle = 30.0

    if preset is not None:
        if preset == "reset":
            _fit_camera(view, id, bounds=patch_bounds)
        else:
            # Set look direction (camera AT axis or iso octant, looking
            # back at focal), then ResetCamera to fit. NOTE: ParaView
            # 5.13's `ResetActiveCameraToPositiveX/...` proxy methods only
            # set the direction without fitting in this build, so we do
            # both manually.
            directions = {
                "+x": ([1, 0, 0], [0, 0, 1]),
                "-x": ([-1, 0, 0], [0, 0, 1]),
                "+y": ([0, 1, 0], [0, 0, 1]),
                "-y": ([0, -1, 0], [0, 0, 1]),
                "+z": ([0, 0, 1], [0, 1, 0]),
                "-z": ([0, 0, -1], [0, 1, 0]),
                "iso+x+y+z": ([1, 1, 1], [0, 0, 1]),
                "iso+x+y-z": ([1, 1, -1], [0, 0, 1]),
                "iso+x-y+z": ([1, -1, 1], [0, 0, 1]),
                "iso+x-y-z": ([1, -1, -1], [0, 0, 1]),
                "iso-x+y+z": ([-1, 1, 1], [0, 0, 1]),
                "iso-x+y-z": ([-1, 1, -1], [0, 0, 1]),
                "iso-x-y+z": ([-1, -1, 1], [0, 0, 1]),
                "iso-x-y-z": ([-1, -1, -1], [0, 0, 1]),
            }
            if preset not in directions:
                raise ValueError(f"unknown preset {preset!r}")
            dir_vec, up_vec = directions[preset]
            view.CameraFocalPoint = [0, 0, 0]
            view.CameraPosition = dir_vec
            view.CameraViewUp = up_vec
            _fit_camera(view, id, bounds=patch_bounds)

    if toward is not None:
        vec = _check_vec3(toward, "toward", nonzero=True)
        n = (vec[0] ** 2 + vec[1] ** 2 + vec[2] ** 2) ** 0.5
        ux, uy, uz = vec[0] / n, vec[1] / n, vec[2] / n
        view.CameraFocalPoint = [0, 0, 0]
        view.CameraPosition = [-ux, -uy, -uz]  # camera opposite the look direction
        view.CameraViewUp = [0, 1, 0] if abs(uz) > 0.99 else [0, 0, 1]
        _fit_camera(view, id, bounds=patch_bounds)

    # `patch` with no orientation change: just re-frame onto it.
    if patch_bounds is not None and preset is None and toward is None:
        _fit_camera(view, id, bounds=patch_bounds)

    if position is not None:
        view.CameraPosition = _check_vec3(position, "position")
    if focal is not None:
        view.CameraFocalPoint = _check_vec3(focal, "focal")
    if up is not None:
        view.CameraViewUp = _check_vec3(up, "up", nonzero=True)

    # If both position and focal were set in this call, reject coincident points.
    if position is not None and focal is not None:
        p = list(view.CameraPosition)
        f = list(view.CameraFocalPoint)
        if p == f:
            raise ValueError("position and focal cannot be the same point")

    import math
    cam = view.GetActiveCamera() if hasattr(view, "GetActiveCamera") else None
    if cam is not None:
        if zoom is not None:
            z = float(zoom)
            if not math.isfinite(z) or z <= 0:
                raise ValueError(f"zoom must be a positive finite number, got {zoom!r}")
            cam.Zoom(z)
        if dolly is not None:
            d = float(dolly)
            if not math.isfinite(d):
                raise ValueError(f"dolly must be finite, got {dolly!r}")
            cam.Dolly(d)
        if azimuth is not None:
            cam.Azimuth(_check_finite([azimuth], "azimuth")[0])
        if elevation is not None:
            cam.Elevation(_check_finite([elevation], "elevation")[0])
        if roll is not None:
            cam.Roll(_check_finite([roll], "roll")[0])

    if parallel is not None:
        view.CameraParallelProjection = 1 if parallel else 0
    if parallel_scale is not None:
        ps = _check_finite([parallel_scale], "parallel_scale")[0]
        if ps <= 0:
            raise ValueError(f"parallel_scale must be positive, got {parallel_scale!r}")
        view.CameraParallelScale = ps

    Render()
    return get_camera()


# ---------------------------------------------------------------------------
# Pipeline lifecycle
# ---------------------------------------------------------------------------

def load_dataset(path, type_=None):
    from paraview.simple import OpenDataFile, Show, Render, ResetCamera, GetActiveView
    if not os.path.isabs(path):
        path = os.path.abspath(os.path.join(BASE_DIR, path))
    src = OpenDataFile(path)
    if src is None:
        raise RuntimeError(f"OpenDataFile returned None for {path}")
    view = GetActiveView()
    Show(src, view)
    ResetCamera(view)
    Render()
    return {**_source_descriptor(src), "path": path}


# Alias kept for the env-driven auto-loader at startup.
load_case = load_dataset


def create_geometry_source(type_, **kwargs):
    from paraview.simple import (
        Sphere, Cone, Cylinder, Plane, Box, Line, Show, Render, GetActiveView,
    )
    t = (type_ or "").lower()
    if t == "sphere":
        s = Sphere()
        if "center" in kwargs:
            s.Center = list(kwargs["center"])
        if "radius" in kwargs:
            s.Radius = float(kwargs["radius"])
    elif t == "cone":
        s = Cone()
        if "center" in kwargs:
            s.Center = list(kwargs["center"])
        if "radius" in kwargs:
            s.Radius = float(kwargs["radius"])
        if "height" in kwargs:
            s.Height = float(kwargs["height"])
    elif t == "cylinder":
        s = Cylinder()
        if "center" in kwargs:
            s.Center = list(kwargs["center"])
        if "radius" in kwargs:
            s.Radius = float(kwargs["radius"])
        if "height" in kwargs:
            s.Height = float(kwargs["height"])
    elif t == "plane":
        s = Plane()
        if "origin" in kwargs:
            s.Origin = list(kwargs["origin"])
        if "point1" in kwargs:
            s.Point1 = list(kwargs["point1"])
        if "point2" in kwargs:
            s.Point2 = list(kwargs["point2"])
    elif t == "box":
        s = Box()
        if "bounds" in kwargs:
            b = list(kwargs["bounds"])
            if len(b) != 6:
                raise ValueError("box bounds must be 6 floats")
            s.XLength = b[1] - b[0]
            s.YLength = b[3] - b[2]
            s.ZLength = b[5] - b[4]
            s.Center = [(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2]
        if "center" in kwargs:
            s.Center = list(kwargs["center"])
    elif t == "line":
        s = Line()
        if "point1" in kwargs:
            s.Point1 = list(kwargs["point1"])
        if "point2" in kwargs:
            s.Point2 = list(kwargs["point2"])
    else:
        raise ValueError(f"unknown geometry type: {type_!r}")
    Show(s, GetActiveView())
    Render()
    return _source_descriptor(s)


def set_active_source(source_id):
    from paraview.simple import SetActiveSource, GetSources
    src = _find_proxy_by_id(source_id)
    if src is None:
        raise ValueError(f"no source with id {source_id}")
    SetActiveSource(src)
    name = next((n for (n, gid) in GetSources().keys() if gid == source_id), None)
    return {"id": source_id, "name": name}


def set_active_view(view_id):
    from paraview.simple import SetActiveView, Render
    v = _find_view_by_id(view_id)
    if v is None:
        raise ValueError(f"no view with id {view_id}")
    SetActiveView(v)
    Render(v)
    return {"id": view_id, "type": v.SMProxy.GetXMLName()}


def delete_source(source_id):
    from paraview.simple import Delete, Show, Render, GetActiveView, GetSources
    src = _find_proxy_by_id(source_id)
    if src is None:
        raise ValueError(f"no source with id {source_id}")
    # Capture the inputs of the proxy being deleted, and resolve them to live
    # proxies so we can re-show them after the delete (typical "undo a filter"
    # back-track expects the parent to reappear).
    parent_ids = _input_ids(src)
    parents = [p for p in (_find_proxy_by_id(pid) for pid in parent_ids) if p is not None]
    Delete(src)
    view = GetActiveView()
    re_shown = []
    if view is not None and parents:
        # Only re-show parents that have no other visible downstream consumers.
        all_sources = list(GetSources().values())
        for parent in parents:
            pid = parent.SMProxy.GetGlobalIDAsString()
            has_visible_child = False
            for other in all_sources:
                if other is parent:
                    continue
                if pid in _input_ids(other):
                    try:
                        from paraview.simple import GetDisplayProperties
                        rep = GetDisplayProperties(other, view=view)
                        if rep is not None and bool(int(rep.Visibility)):
                            has_visible_child = True
                            break
                    except Exception:
                        continue
            if not has_visible_child:
                try:
                    Show(parent, view)
                    re_shown.append(pid)
                except Exception:
                    pass
    _hide_unused_scalar_bars()  # clear legends orphaned by the deleted source
    Render()
    return {"deleted": source_id, "re_shown": re_shown}


# ---------------------------------------------------------------------------
# Filters — each creates a new pipeline node, makes it active, hides input.
# ---------------------------------------------------------------------------

def apply_slice_filter(normal, origin=None, input_id=None):
    from paraview.simple import Slice
    n = _check_vec3(normal, "normal", nonzero=True)
    src = _resolve_target_source(input_id)
    s = Slice(Input=src)
    s.SliceType = "Plane"
    if origin is not None:
        s.SliceType.Origin = _check_vec3(origin, "origin")
    # else: BoundsDomain default fires → input bbox center
    s.SliceType.Normal = n
    _show_and_hide_input(s, src)
    return _source_descriptor(s, "Slice")


def apply_clip_filter(normal, origin=None, input_id=None, invert=False, crinkle=False):
    from paraview.simple import Clip
    n = _check_vec3(normal, "normal", nonzero=True)
    src = _resolve_target_source(input_id)
    c = Clip(Input=src)
    c.ClipType = "Plane"
    if origin is not None:
        c.ClipType.Origin = _check_vec3(origin, "origin")
    # else: BoundsDomain default fires → input bbox center
    c.ClipType.Normal = n
    c.Invert = bool(invert)
    if crinkle:
        try:
            c.Crinkleclip = 1
        except Exception:
            pass
    _show_and_hide_input(c, src)
    hint_side = "the clip normal points toward" if invert else "opposite the clip normal"
    return {
        **_source_descriptor(c, "Clip"),
        "framing_hint": (
            f"Hint: To frame the cut face, place the camera in the "
            f"half-space {hint_side}."
        ),
    }


def apply_threshold_filter(array, range_, component=None, input_id=None):
    from paraview.simple import Threshold
    src = _resolve_target_source(input_id)
    assoc = _detect_association(src, array)
    t = Threshold(Input=src)
    t.Scalars = [assoc, array]
    try:
        t.LowerThreshold = float(range_[0])
        t.UpperThreshold = float(range_[1])
    except AttributeError:
        # Older API
        t.ThresholdRange = [float(range_[0]), float(range_[1])]
    if component is not None:
        try:
            t.SelectedComponent = int(component)
        except Exception:
            pass
    _show_and_hide_input(t, src)
    return _source_descriptor(t, "Threshold")


def apply_contour_filter(array, values, input_id=None):
    from paraview.simple import Contour, CellDatatoPointData, Delete
    src = _resolve_target_source(input_id)
    assoc = _detect_association(src, array)
    contour_input = src
    cell_to_point = None
    if assoc == "CELLS":
        # Contour requires point data; auto-insert CellDatatoPointData so the
        # caller doesn't have to (and so we don't crash ParaView).
        cell_to_point = CellDatatoPointData(Input=src)
        cell_to_point.PassCellData = 1
        contour_input = cell_to_point
        assoc = "POINTS"
    try:
        c = Contour(Input=contour_input)
        c.ContourBy = [assoc, array]
        c.Isosurfaces = [float(v) for v in values]
        _show_and_hide_input(c, src)
        return _source_descriptor(c, "Contour")
    except Exception:
        if cell_to_point is not None:
            try:
                Delete(cell_to_point)
            except Exception:
                pass
        raise


def apply_glyph_filter(array, scale=None, type_="arrow", max_points=None, input_id=None):
    from paraview.simple import Glyph
    src = _resolve_target_source(input_id)
    g = Glyph(Input=src)
    glyph_map = {
        "arrow": "Arrow", "sphere": "Sphere", "cone": "Cone",
        "2d_glyph": "2D Glyph", "cylinder": "Cylinder",
    }
    g.GlyphType = glyph_map.get((type_ or "arrow").lower(), "Arrow")
    assoc = _detect_association(src, array)
    g.OrientationArray = [assoc, array]
    g.ScaleArray = [assoc, array]
    if scale is not None:
        try:
            g.ScaleFactor = float(scale)
        except Exception:
            pass
    if max_points is not None:
        try:
            g.MaximumNumberOfSamplePoints = int(max_points)
        except Exception:
            pass
    _show_and_hide_input(g, src)
    return _source_descriptor(g, "Glyph")


def apply_streamtracer_filter(array, seed_type, p0=None, p1=None,
                              center=None, radius=None, resolution=None,
                              max_length=None, direction=None, input_id=None):
    from paraview.simple import StreamTracer
    src = _resolve_target_source(input_id)
    s = StreamTracer(Input=src)
    assoc = _detect_association(src, array)
    s.Vectors = [assoc, array]
    # PV 5.13 SeedType domain: "Line" and "Point Cloud" only.
    # "sphere" is mapped to "point_cloud" — Point Cloud has Center+Radius and
    # produces a sphere of seed points.
    seed = (seed_type or "line").lower()
    if seed == "line":
        s.SeedType = "Line"
        if p0 is not None:
            s.SeedType.Point1 = list(p0)
        if p1 is not None:
            s.SeedType.Point2 = list(p1)
        if resolution is not None:
            try:
                s.SeedType.Resolution = int(resolution)
            except Exception:
                pass
    elif seed in ("point_cloud", "sphere"):
        s.SeedType = "Point Cloud"
        if center is not None:
            try:
                s.SeedType.Center = list(center)
            except Exception:
                pass
        if radius is not None:
            try:
                s.SeedType.Radius = float(radius)
            except Exception:
                pass
        if resolution is not None:
            try:
                s.SeedType.NumberOfPoints = int(resolution)
            except Exception:
                pass
    else:
        raise ValueError(f"unknown seed_type {seed_type!r}; use 'line' or 'point_cloud'")

    if max_length is not None:
        try:
            s.MaximumStreamlineLength = float(max_length)
        except Exception:
            pass
    if direction is not None:
        s.IntegrationDirection = {
            "forward": "FORWARD", "backward": "BACKWARD", "both": "BOTH",
        }.get(direction.lower(), "BOTH")
    _show_and_hide_input(s, src)
    return _source_descriptor(s, "StreamTracer")


def apply_calculator_filter(result, expr, field="point", input_id=None):
    from paraview.simple import Calculator
    src = _resolve_target_source(input_id)
    c = Calculator(Input=src)
    c.AttributeType = "Point Data" if (field or "point").lower() == "point" else "Cell Data"
    c.ResultArrayName = result
    c.Function = expr
    _show_and_hide_input(c, src)
    return _source_descriptor(c, "Calculator")


def compute_gradient_filter(array, input_id=None):
    import paraview.simple as pvs
    src = _resolve_target_source(input_id)
    assoc = _detect_association(src, array)
    # ParaView versions differ: try Gradient (modern), fall back to legacy
    # GradientOfUnstructuredDataSet if it exists.
    if hasattr(pvs, "Gradient"):
        g = pvs.Gradient(Input=src)
    elif hasattr(pvs, "GradientOfUnstructuredDataSet"):
        g = pvs.GradientOfUnstructuredDataSet(Input=src)
    else:
        raise RuntimeError("No Gradient filter available in this ParaView build")
    # Property name varies across versions: ScalarArray / SelectInputScalars / Scalars
    for prop in ("ScalarArray", "SelectInputScalars", "Scalars"):
        try:
            setattr(g, prop, [assoc, array])
            break
        except Exception:
            continue
    _show_and_hide_input(g, src)
    return _source_descriptor(g, "Gradient")


def extract_block(name, input_id=None):
    from paraview.simple import ExtractBlock
    src = _resolve_target_source(input_id)
    # Resolve the name (leaf 'inlet' or slashed 'patch/inlet') to its
    # data-assembly selector path so the form reported by get_openfoam_patches
    # works. Fall back to the legacy name-based selectors for sources without a
    # hierarchy or names not present in the loaded data.
    src.UpdatePipeline()
    path = _block_path_in(src.GetDataInformation().GetHierarchy(), name)
    selectors = [path] if path is not None else [f"//{name}", name]
    eb = ExtractBlock(Input=src)
    # Multiple ParaView versions expose this with different property names.
    for prop in ("Selectors", "BlockSelectors"):
        try:
            setattr(eb, prop, selectors)
            break
        except Exception:
            continue
    _show_and_hide_input(eb, src)
    # Report counts so a silent empty extraction (commonly an unloaded
    # OpenFOAM patch) is visible instead of a blank, valid-looking source.
    # These come from the data information — server-side metadata, no Fetch.
    eb.UpdatePipeline()
    di = eb.GetDataInformation()
    n_cells, n_points = di.GetNumberOfCells(), di.GetNumberOfPoints()
    out = {**_source_descriptor(eb, "ExtractBlock"),
           "num_cells": n_cells, "num_points": n_points}
    if n_cells == 0 and n_points == 0:
        s = _source_descriptor(src)
        out["hint"] = (
            f"block {name!r} extracted from {s.get('name')!r} "
            f"(id {s.get('id')}, type {s.get('type')}) but is empty. "
            f"extract_block targets the ACTIVE source when input_id is omitted, "
            f"and paraview_exec or creating a filter can silently move the active "
            f"source off the OpenFOAM reader. If {s.get('name')!r} is not the "
            f"reader, re-run extract_block with input_id set to the OpenFOAMReader "
            f"(get_pipeline marks it and flags the active source). Otherwise the "
            f"patch is genuinely not loaded — use get_openfoam_patches / "
            f"set_openfoam_patches to enable it, then extract again."
        )
    return out


def extract_surface(input_id=None):
    from paraview.simple import ExtractSurface
    src = _resolve_target_source(input_id)
    es = ExtractSurface(Input=src)
    _show_and_hide_input(es, src)
    return _source_descriptor(es, "ExtractSurface")


def extract_selection_filter(input_id=None):
    from paraview.simple import ExtractSelection
    src = _resolve_target_source(input_id)
    es = ExtractSelection(Input=src)
    _show_and_hide_input(es, src)
    return _source_descriptor(es, "ExtractSelection")


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def set_representation(mode, input_id=None):
    from paraview.simple import GetDisplayProperties, GetActiveView, Render
    src = _resolve_target_source(input_id)
    rep = GetDisplayProperties(src, view=GetActiveView())
    rep.Representation = mode
    Render()
    return {"id": src.SMProxy.GetGlobalIDAsString(), "representation": mode}


def set_visibility(mode, input_id=None):
    from paraview.simple import (
        GetDisplayProperties, GetActiveView, Show, Hide, Render,
    )
    src = _resolve_target_source(input_id)
    view = GetActiveView()
    rep = GetDisplayProperties(src, view=view)
    cur = bool(int(rep.Visibility)) if rep is not None else False
    if mode == "show":
        Show(src, view)
        new = True
    elif mode == "hide":
        Hide(src, view)
        new = False
    elif mode == "toggle":
        if cur:
            Hide(src, view)
            new = False
        else:
            Show(src, view)
            new = True
    else:
        raise ValueError(f"unknown visibility mode: {mode}")
    Render()
    return {"id": src.SMProxy.GetGlobalIDAsString(), "visible": new}


def set_opacity(value, input_id=None):
    from paraview.simple import GetDisplayProperties, GetActiveView, Render
    src = _resolve_target_source(input_id)
    rep = GetDisplayProperties(src, view=GetActiveView())
    v = float(value)
    if not 0.0 <= v <= 1.0:
        raise ValueError(f"opacity must be in [0,1], got {v}")
    rep.Opacity = v
    Render()
    return {"id": src.SMProxy.GetGlobalIDAsString(), "opacity": v}


def color_by_array(array, component=None, input_id=None):
    from paraview.simple import (
        ColorBy, GetDisplayProperties, GetActiveView, Render,
    )
    src = _resolve_target_source(input_id)
    view = GetActiveView()
    rep = GetDisplayProperties(src, view=view)
    association = _detect_association(src, array)
    if component is not None:
        ColorBy(rep, (association, array, int(component)))
    else:
        ColorBy(rep, (association, array))
    rep.RescaleTransferFunctionToDataRange(True, False)
    rep.SetScalarBarVisibility(view, True)
    _hide_unused_scalar_bars()  # drop the previously-colored array's stale bar
    Render()
    return {
        "id": src.SMProxy.GetGlobalIDAsString(),
        "array": array,
        "association": association,
        "component": component,
    }


def set_solid_color(rgb, input_id=None):
    from paraview.simple import GetDisplayProperties, GetActiveView, Render
    src = _resolve_target_source(input_id)
    if len(rgb) != 3:
        raise ValueError("rgb must be 3 floats")
    color = [float(c) for c in rgb]
    if any(c < 0 or c > 1 for c in color):
        raise ValueError("rgb components must be in [0,1]")
    rep = GetDisplayProperties(src, view=GetActiveView())
    # Disable scalar coloring directly. ColorBy(rep, None) fails on PV 5.13.3
    # because servermanager rejects "NONE" as an association string.
    try:
        rep.ColorArrayName = ["", ""]
    except Exception:
        pass
    rep.AmbientColor = color
    rep.DiffuseColor = color
    _hide_unused_scalar_bars()  # going back to solid drops this source's bar
    Render()
    return {"id": src.SMProxy.GetGlobalIDAsString(), "color": color}


def configure_colormap(preset=None, range_=None, rescale=None, log=None,
                       input_id=None):
    from paraview.simple import (
        GetDisplayProperties, GetActiveView, GetColorTransferFunction, Render,
    )
    src = _resolve_target_source(input_id)
    rep = GetDisplayProperties(src, view=GetActiveView())
    car = rep.GetPropertyValue("ColorArrayName")
    if not (car and len(car) >= 2 and car[1]):
        raise RuntimeError(
            "source is not colored by an array; call color_by_array first"
        )
    array_name = car[1]
    lut = GetColorTransferFunction(array_name)

    if preset is not None:
        try:
            lut.ApplyPreset(preset, True)
        except Exception as e:
            raise ValueError(f"could not apply preset {preset!r}: {e}")
    if range_ is not None:
        if len(range_) != 2:
            raise ValueError("range must be 2 floats")
        lut.RescaleTransferFunction(float(range_[0]), float(range_[1]))
    if rescale is not None:
        if rescale == "auto":
            rep.RescaleTransferFunctionToDataRange(False, True)
        elif rescale == "visible":
            rep.RescaleTransferFunctionToDataRange(True, False)
        elif rescale == "all_timesteps":
            rep.RescaleTransferFunctionToDataRangeOverTime()
        else:
            raise ValueError(f"unknown rescale: {rescale}")
    if log is not None:
        try:
            lut.UseLogScale = 1 if log else 0
        except Exception:
            pass
    Render()
    rng = None
    if hasattr(lut, "RGBPoints"):
        pts = list(lut.RGBPoints)
        # RGBPoints is [scalar, R, G, B, scalar, R, G, B, ...]; the
        # transfer-function range is the first and last scalar entries.
        if len(pts) >= 8:
            rng = [pts[0], pts[-4]]
        elif len(pts) >= 4:
            rng = [pts[0], pts[0]]
    return {
        "id": src.SMProxy.GetGlobalIDAsString(),
        "array": array_name,
        "preset": preset,
        "range": rng,
    }


# ---------------------------------------------------------------------------
# OpenFOAM patches
# ---------------------------------------------------------------------------

def _find_openfoam_reader():
    from paraview.simple import GetSources
    for proxy in GetSources().values():
        if proxy.SMProxy.GetXMLName() == "OpenFOAMReader":
            return proxy
    return None


def _openfoam_reader_for(input_id):
    if input_id:
        src = _find_proxy_by_id(input_id)
        if src is None:
            raise ValueError(f"no source with id {input_id}")
        return src
    src = _find_openfoam_reader()
    if src is None:
        raise RuntimeError("no OpenFOAMReader in pipeline")
    return src


def get_openfoam_patches(input_id=None):
    src = _openfoam_reader_for(input_id)
    p = src.GetProperty("MeshRegions")
    if p is None:
        raise RuntimeError("source has no MeshRegions property")
    enabled = list(src.GetPropertyValue("MeshRegions") or [])
    available = list(p.Available)
    return {"enabled": enabled, "available": available}


def set_openfoam_patches(enable=None, disable=None, input_id=None):
    from paraview.simple import Render
    src = _openfoam_reader_for(input_id)
    p = src.GetProperty("MeshRegions")
    if p is None:
        raise RuntimeError("source has no MeshRegions property")
    available = list(p.Available)
    current = set(src.GetPropertyValue("MeshRegions") or [])
    enable = enable or []
    disable = disable or []
    for name in enable:
        if name not in available:
            raise ValueError(f"unknown patch {name!r}; available: {available}")
        current.add(name)
    for name in disable:
        current.discard(name)
    src.MeshRegions = sorted(current)
    src.UpdatePipeline()
    Render()
    return {"enabled": list(src.GetPropertyValue("MeshRegions") or []), "available": available}


def set_read_zero_time(enable=True, input_id=None):
    """Toggle the OpenFOAM reader's reading of the 0/ time directory.

    The reader skips 0/ by default (SkipZeroTime=1). checkMesh writes its
    quality fields (skewness, nonOrthoAngle, …) into the latest time — which
    for a mesh-only case is 0/ — so they stay invisible until zero time is
    read. Returns the loaded array names so the effect is visible.
    """
    from paraview.simple import Render
    src = _openfoam_reader_for(input_id)
    if src.GetProperty("SkipZeroTime") is None:
        raise RuntimeError("source has no SkipZeroTime property (not an OpenFOAM reader)")
    src.SkipZeroTime = 0 if enable else 1
    src.UpdatePipelineInformation()
    src.UpdatePipeline()
    Render()
    di = src.GetDataInformation()

    def _names(info):
        try:
            return [_array_info_at(info, i).GetName() for i in range(info.GetNumberOfArrays())]
        except Exception:
            return []

    return {
        "read_zero_time": bool(enable),
        "cell_arrays": _names(src.GetCellDataInformation()),
        "point_arrays": _names(src.GetPointDataInformation()),
    }


# ---------------------------------------------------------------------------
# Problem-cell overlays — topoSets from constant/polyMesh/sets/<name>
# ---------------------------------------------------------------------------

_FOAM_CLASS_RE = re.compile(r"^\s*class\s+(\w+)\s*;", re.MULTILINE)


def _read_foam_label_list(path):
    """Parse an OpenFOAM label-list file (cellSet/faceSet/owner/…), ASCII or
    binary.

    Returns (klass, ids). Handles gzip (.gz). ASCII vs binary is decided by
    SNIFFING THE DATA, not the header `format` keyword: OpenFOAM stamps `format
    binary` in topoSet/checkMesh set headers even when the label list is written
    ASCII (the header lies), so trusting it sends an ASCII set down the binary
    path and frombuffer reads garbage. The header still supplies `class` and the
    `arch "LSB;label=32;…"` line — from which the binary integer width (32→4,
    64→8 bytes) and endianness (LSB→'<', MSB→'>') are taken. ASCII handles // and
    /* */ comments and both 'N ( a b c )' and inline layouts. `klass` is the
    FoamFile `class` or None.
    """
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rb") as fh:
        raw = fh.read()

    # The FoamFile header dict is ASCII even in binary files. Decode just it.
    hb = raw.find(b"{")
    he = raw.find(b"}", hb) if hb >= 0 else -1
    header = (raw[: he + 1] if he >= 0 else raw[:4096]).decode("latin-1", "replace")
    m = _FOAM_CLASS_RE.search(header)
    klass = m.group(1) if m else None
    arch_m = re.search(r'arch\s+"([^"]*)"', header)
    arch = arch_m.group(1) if arch_m else ""
    width = 8 if "label=64" in arch else 4
    endian = ">" if arch.startswith("MSB") else "<"

    # Data section follows the header dict's closing brace.
    rest = raw[he + 1:] if he >= 0 else raw
    op = rest.find(b"(")
    if op < 0:
        raise ValueError(f"no '( … )' data block in {path}")

    # Sniff the data to choose ASCII vs binary (the header `format` is unreliable
    # for sets — see docstring). Distinguish by PRINTABILITY: ASCII label data
    # and the trailing FoamFile comment are all printable, while a binary blob
    # has control/high bytes (nulls in small labels, high bytes in large) within
    # the first few labels. A digit-only test would misfire on the `// *** //`
    # footer of a short set, whose bytes fall inside the 128-byte window.
    sample = rest[op + 1: op + 1 + 128]
    is_binary = any((b < 32 and b not in (9, 10, 13)) or b > 126 for b in sample)

    if not is_binary:
        # ASCII: integers between '(' and the final ')'.
        cl = rest.rfind(b")")
        if cl <= op:
            raise ValueError(f"no '( … )' data block in {path}")
        body = rest[op + 1: cl].decode("latin-1", "replace")
        body = re.sub(r"//[^\n]*", "", body)
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
        return klass, [int(tok) for tok in body.split()]

    # Binary: the element count is the ASCII integer just before '(', then
    # exactly count*width raw bytes. Do NOT scan for ')': a label byte can equal
    # its character code, so the closing paren is found by length, not search.
    import numpy as np
    pre = rest[:op].decode("latin-1", "replace")
    pre = re.sub(r"//[^\n]*", "", pre)
    pre = re.sub(r"/\*.*?\*/", "", pre, flags=re.DOTALL)
    counts = re.findall(r"\d+", pre)
    if not counts:
        raise ValueError(f"binary list in {path} has no element count before '('")
    count = int(counts[-1])
    data = rest[op + 1: op + 1 + count * width]
    if len(data) < count * width:
        raise ValueError(
            f"binary list in {path} truncated: expected {count * width} bytes, "
            f"got {len(data)}"
        )
    return klass, np.frombuffer(data, dtype=np.dtype(f"{endian}i{width}")).tolist()


def _polymesh_file(case_dir, name):
    """Resolve a constant/polyMesh file, trying the plain and gzipped form."""
    base = os.path.join(case_dir, "constant", "polyMesh", name)
    for cand in (base, base + ".gz"):
        if os.path.exists(cand):
            return cand
    return None


def _case_dir_for_reader(reader):
    """Directory of the OpenFOAM case behind a reader (parent of the .foam)."""
    fname = reader.GetPropertyValue("FileName")
    if not fname:
        raise RuntimeError("OpenFOAM reader has no FileName; cannot locate sets/")
    return os.path.dirname(os.path.abspath(fname))


def highlight_problem_cells(set_name, input_id=None):
    """Highlight an OpenFOAM topoSet (e.g. checkMesh problem cells) as a new
    overlay source layered on the scene. Existing sources are left untouched.

    Reads constant/polyMesh/sets/<set_name> off disk and maps it to cells of
    the OpenFOAM reader's internalMesh (cell numbering is 1:1 with OpenFOAM on
    this build), then extracts those cells into a fresh solid red source:

    - cellSet → those cells.
    - faceSet → the OWNER CELL of each face. A face is an interface between two
      cells, not a renderable volume, so this locates each bad face to within
      one cell rather than drawing the face itself; the returned `note` says so.
    - any other class (pointSet, …) → not supported; raises with guidance.

    Returns a descriptor of the new source plus counts and, for faceSets, a
    `note` spelling out the owner-cell substitution so it is never a surprise.
    """
    from paraview.simple import (
        ColorBy, ExtractBlock, ExtractSelection, GetActiveView,
        IDSelectionSource, Render, Show,
    )
    reader = _openfoam_reader_for(input_id)
    case_dir = _case_dir_for_reader(reader)

    set_path = _polymesh_file(case_dir, os.path.join("sets", set_name))
    if set_path is None:
        raise FileNotFoundError(
            f"set {set_name!r} not found under "
            f"{case_dir}/constant/polyMesh/sets (tried plain and .gz). "
            f"checkMesh writes problem-cell sets there; run it (or topoSet), "
            f"or correct the name."
        )
    klass, ids = _read_foam_label_list(set_path)
    klass = klass or "cellSet"

    note = None
    if klass == "cellSet":
        cell_ids = sorted(set(ids))
    elif klass == "faceSet":
        owner_path = _polymesh_file(case_dir, "owner")
        if owner_path is None:
            raise FileNotFoundError(
                f"set {set_name!r} is a faceSet; mapping faces to cells needs "
                f"constant/polyMesh/owner, not found under {case_dir}."
            )
        _, owner = _read_foam_label_list(owner_path)
        try:
            cell_ids = sorted({owner[f] for f in ids})
        except IndexError:
            raise RuntimeError(
                f"faceSet {set_name!r} references a face id beyond owner "
                f"({len(owner)} faces); set and mesh look out of sync."
            )
        note = (
            f"faceSet: a face is not a renderable volume, so this highlights "
            f"the owner cell of each face ({len(ids)} faces → {len(cell_ids)} "
            f"owner cells). Location is exact to within one cell, not the face "
            f"itself."
        )
    else:
        raise ValueError(
            f"set {set_name!r} has class {klass!r}; only cellSet and faceSet "
            f"are supported (pointSet and other topoSet types are not)."
        )

    if not cell_ids:
        return {"set": set_name, "kind": klass, "num_cells_extracted": 0,
                "hint": f"set {set_name!r} is empty; nothing to highlight."}

    # Extract internalMesh first so the selection ids are the OpenFOAM internal
    # cell numbering (the set's numbering), not multiblock-composite indices.
    reader.UpdatePipeline()
    internal = ExtractBlock(Input=reader)
    block_path = _block_path_in(
        reader.GetDataInformation().GetHierarchy(), "internalMesh")
    selectors = [block_path] if block_path is not None else [
        "//internalMesh", "internalMesh"]
    for prop in ("Selectors", "BlockSelectors"):
        try:
            setattr(internal, prop, selectors)
            break
        except Exception:
            continue
    internal.UpdatePipeline()
    if internal.GetDataInformation().GetNumberOfCells() == 0:
        raise RuntimeError(
            "internalMesh has no cells — it is probably not loaded. Enable it "
            "with set_openfoam_patches(enable=['internalMesh']) and retry."
        )

    sel = IDSelectionSource()
    sel.FieldType = "CELL"
    flat = []
    for cid in cell_ids:
        flat.extend((0, int(cid)))
    sel.IDs = flat
    sel.UpdatePipeline()
    extracted = ExtractSelection(Input=internal, Selection=sel)
    extracted.UpdatePipeline()
    n_extracted = extracted.GetDataInformation().GetNumberOfCells()

    view = GetActiveView()
    rep = Show(extracted, view)
    rep.Representation = "Surface With Edges"
    # Saturated red so the overlay reads against the existing scene; the agent
    # refines color/opacity/representation via the normal display verbs.
    # An OpenFOAM case with solved fields makes ParaView auto-colour the
    # extraction by a field (e.g. 'p'), which overrides the solid colour — so
    # disable scalar colouring first. ColorBy(rep, None) clears it on PV 5.13.3
    # (it leaves the array name empty); fall back to the property assignment.
    try:
        ColorBy(rep, None)
    except Exception:
        try:
            rep.ColorArrayName = ["", ""]
        except Exception:
            pass
    rep.AmbientColor = [0.9, 0.1, 0.1]
    rep.DiffuseColor = [0.9, 0.1, 0.1]
    # "Surface With Edges" defaults to a blue edge colour that visually
    # swamps the red fill on thin/sparse cells (they read as mis-coloured).
    # Black edges keep the cells legible as red without that confusion.
    try:
        rep.EdgeColor = [0.0, 0.0, 0.0]
    except Exception:
        pass
    Render()

    out = {
        **_source_descriptor(extracted, "ProblemCells"),
        "set": set_name,
        "kind": klass,
        "num_in_set": len(ids),
        "num_cells_extracted": n_extracted,
    }
    if note:
        out["note"] = note
    if klass == "cellSet" and n_extracted != len(cell_ids):
        out["hint"] = (
            f"extracted {n_extracted} cells but the set lists {len(cell_ids)} — "
            f"the reader's internalMesh numbering may not match the set (e.g. a "
            f"decomposed/polyhedral build). Treat the overlay as approximate, "
            f"or run `foamToVTK -cellSet {set_name} -time constant` and "
            f"load_dataset the resulting .vtu."
        )
    return out


# ---------------------------------------------------------------------------
# Quantitative reads
# ---------------------------------------------------------------------------

def probe_point(point, input_id=None):
    from paraview.simple import ProbeLocation, Delete, GetActiveSource, SetActiveSource
    src = _resolve_target_source(input_id)
    pt = _check_finite(point, "point")
    if len(pt) != 3:
        raise ValueError("point must be 3 floats")
    # Creating ProbeLocation makes it the active source; Delete(probe) does
    # not restore the previous active. Capture it now and restore after.
    prev_active = GetActiveSource()
    probe = ProbeLocation(Input=src, ProbeType="Fixed Radius Point Source")
    try:
        probe.ProbeType.Center = pt
        probe.ProbeType.NumberOfPoints = 1
        probe.UpdatePipeline()

        # Read sampled values from the proxy's DataInformation rather than
        # servermanager.Fetch + GetTuple. On OpenFOAM multiblock data the
        # fetched arrays come back with corrupted names ("float") and dead
        # data pointers, so GetTuple() segfaults and takes the whole bridge
        # down (a SIGSEGV can't be caught). DataInformation is computed
        # ParaView-side and is crash-safe — the same path get_source_info
        # uses. ProbeLocation deposits all sampled fields (point AND cell
        # data from the source) onto its single output point, so the value
        # of each array is its single-point component range [v, v].
        di = probe.GetPointDataInformation()
        arrays = {}
        valid = True
        for i in range(di.GetNumberOfArrays()):
            ai = di.GetArray(i)
            if ai is None:
                continue
            name = ai.GetName()
            ncomp = ai.GetNumberOfComponents()
            if name == "vtkValidPointMask":
                # 0 -> the point fell outside the dataset; values are unset.
                valid = ai.GetComponentRange(0)[0] != 0
                continue
            if ncomp == 1:
                arrays[name] = ai.GetComponentRange(0)[0]
            else:
                arrays[name] = [ai.GetComponentRange(c)[0] for c in range(ncomp)]
        return {
            "point": pt,
            "valid": valid,
            "arrays": arrays,
        }
    finally:
        try:
            Delete(probe)
        except Exception:
            pass
        if prev_active is not None:
            try:
                SetActiveSource(prev_active)
            except Exception:
                pass


def integrate_variables(input_id=None):
    # Read the integrated values from DataInformation rather than
    # servermanager.Fetch + GetTuple, which segfaults on corrupt OpenFOAM
    # multiblock arrays (see _integrate_via_datainfo / probe_point).
    src = _resolve_target_source(input_id)
    by_assoc, measure = _integrate_via_datainfo(src)
    # Collapse (assoc, name) -> name, preferring the cell integral (OpenFOAM
    # fields are cell-native, so the cell integral is the meaningful one).
    integrals = {}
    for assoc in ("cell", "point"):
        for (a, name), val in by_assoc.items():
            if a == assoc and name not in integrals:
                integrals[name] = val
    return {
        "volume_or_area": measure,
        "integrals": integrals,
    }


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def save_screenshot(out_path, hide_widgets=True):
    from paraview.simple import (
        SaveScreenshot, GetActiveView, GetActiveSource, Render,
        HideInteractiveWidgets, ShowInteractiveWidgets,
    )
    view = GetActiveView()

    # Hide the active source's interactive widget so the screenshot
    # doesn't capture draggable plane/box/line handles. Restore after
    # so the live ParaView session looks unchanged. Targets the active
    # source only — in standard ParaView use only the active source's
    # widget is visible at a time.
    active_src = GetActiveSource() if hide_widgets else None
    widget_hidden = False
    if active_src is not None:
        try:
            HideInteractiveWidgets(proxy=active_src)
            widget_hidden = True
        except Exception:
            pass

    Render(view)
    if not os.path.isabs(out_path):
        out_path = os.path.abspath(os.path.join(BASE_DIR, out_path))
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    vw, vh = view.ViewSize
    long_edge = 1600
    if vw >= vh:
        res = [long_edge, max(1, round(long_edge * vh / vw))]
    else:
        res = [max(1, round(long_edge * vw / vh)), long_edge]
    SaveScreenshot(out_path, view, ImageResolution=res)

    if widget_hidden:
        try:
            ShowInteractiveWidgets(proxy=active_src)
        except Exception:
            pass

    Render(view)
    return {"path": out_path, "resolution": res}


def export_snapshot(out_path=None):
    from paraview.simple import GetActiveView, GetActiveSource, SaveScreenshot, Render
    view = GetActiveView()
    Render(view)
    ts = time.strftime("%Y%m%d_%H%M%S")
    png_path = os.path.join(SNAPSHOT_DIR, f"{ts}.png")
    vw, vh = view.ViewSize
    long_edge = 1600
    if vw >= vh:
        res = [long_edge, max(1, round(long_edge * vh / vw))]
    else:
        res = [max(1, round(long_edge * vw / vh)), long_edge]
    SaveScreenshot(png_path, view, ImageResolution=res)
    Render(view)
    camera = {
        "position": list(view.CameraPosition),
        "focal": list(view.CameraFocalPoint),
        "up": list(view.CameraViewUp),
        "view_angle": float(view.CameraViewAngle),
        "view_size": list(view.ViewSize),
    }
    background = {}
    try:
        background["color"] = list(view.GetPropertyValue("Background"))
        background["mode"] = _enum_str(view, "BackgroundColorMode")
        background["use_color_palette"] = bool(view.GetPropertyValue("UseColorPaletteForBackground"))
        if background["mode"] in ("Gradient", "Stereo Skybox"):
            background["color2"] = list(view.GetPropertyValue("Background2"))
    except Exception:
        pass
    active = GetActiveSource()
    state = {
        "timestamp": ts,
        "pipeline": [p for p in list_pipeline(include_properties=True, include_display=True)
                     if p.get("id") in _collect_visible_and_ancestor_ids(view)],
        "active_source_id": active.SMProxy.GetGlobalIDAsString() if active else None,
        "camera": camera,
        "background": background,
        "selection": get_selection_info(),
        "screenshot_path": png_path,
    }
    if out_path:
        if not os.path.isabs(out_path):
            out_path = os.path.abspath(os.path.join(BASE_DIR, out_path))
        parent = os.path.dirname(out_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=repr)
        state["state_path"] = out_path
    return state


# ---------------------------------------------------------------------------
# Escape hatch
# ---------------------------------------------------------------------------

def exec_script(code):
    import contextlib
    import io

    stdout = io.StringIO()
    stderr = io.StringIO()
    response = {"stdout": "", "stderr": "", "result": None, "error": None}

    ns = {"__name__": "__pv_exec__"}
    exec("from paraview.simple import *", ns)
    exec("from paraview import servermanager", ns)
    exec("import vtkmodules.all as vtk", ns)

    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                compiled = compile(code, "<pv-exec>", "eval")
                value = eval(compiled, ns)
                try:
                    response["result"] = repr(value)
                except Exception:
                    response["result"] = "<unrepr-able>"
            except SyntaxError:
                compiled = compile(code, "<pv-exec>", "exec")
                exec(compiled, ns)
                if "result" in ns:
                    try:
                        response["result"] = repr(ns["result"])
                    except Exception:
                        response["result"] = "<unrepr-able>"
    except Exception:
        response["error"] = traceback.format_exc()

    response["stdout"] = stdout.getvalue()
    response["stderr"] = stderr.getvalue()
    return response


# ---------------------------------------------------------------------------
# HTTP routing
# ---------------------------------------------------------------------------

# Map of endpoint path -> (function, list of body keys to extract).
# Each function is wrapped via run_on_gui in do_POST. Body key starting with
# `_REQUIRED_` is required; `_OPTIONAL_` is optional. Body keys without prefix
# pass through as positional args in declared order, or as kwargs.

def _route_table():
    """Build the dispatch table. All endpoints take JSON bodies; functions
    receive **kwargs from the body. Required-key validation is done here."""
    return {
        # State (reads)
        "/get_pipeline":       (get_pipeline, []),
        "/get_source_info":    (get_source_info, []),
        "/get_workspace":      (get_workspace, []),
        "/get_time":           (get_time, []),
        "/get_camera":         (get_camera, []),
        "/get_selection_info": (get_selection_info, []),
        "/get_openfoam_patches": (get_openfoam_patches, []),
        "/probe_point":        (probe_point, ["point"]),
        "/integrate_variables": (integrate_variables, []),
        "/save_screenshot":    (save_screenshot, ["out_path"]),
        "/export_snapshot":    (export_snapshot, []),

        # Sources / pipeline lifecycle
        "/load_dataset":       (load_dataset, ["path"]),
        "/create_geometry_source": (create_geometry_source, ["type_"]),
        "/set_active_source":  (set_active_source, ["source_id"]),
        "/set_active_view":    (set_active_view, ["view_id"]),
        "/delete_source":      (delete_source, ["source_id"]),

        # Filters
        "/apply_slice_filter":     (apply_slice_filter, ["normal"]),
        "/apply_clip_filter":      (apply_clip_filter, ["normal"]),
        "/apply_threshold_filter": (apply_threshold_filter, ["array", "range_"]),
        "/apply_contour_filter":   (apply_contour_filter, ["array", "values"]),
        "/apply_glyph_filter":     (apply_glyph_filter, ["array"]),
        "/apply_streamtracer_filter": (apply_streamtracer_filter, ["array", "seed_type"]),
        "/apply_calculator_filter":(apply_calculator_filter, ["result", "expr"]),
        "/compute_gradient_filter":(compute_gradient_filter, ["array"]),
        "/extract_block":          (extract_block, ["name"]),
        "/extract_surface":        (extract_surface, []),
        "/extract_selection":      (extract_selection_filter, []),
        "/highlight_problem_cells": (highlight_problem_cells, ["set_name"]),

        # Display
        "/set_representation":   (set_representation, ["mode"]),
        "/set_visibility":       (set_visibility, ["mode"]),
        "/set_opacity":          (set_opacity, ["value"]),
        "/color_by_array":       (color_by_array, ["array"]),
        "/set_solid_color":      (set_solid_color, ["rgb"]),
        "/configure_colormap":   (configure_colormap, []),

        # OpenFOAM (write)
        "/set_openfoam_patches": (set_openfoam_patches, []),
        "/set_read_zero_time": (set_read_zero_time, []),

        # Camera / Time (writes)
        "/set_camera": (set_camera, []),
        "/set_time":   (set_time, []),

        # Selection (writes)
        "/create_selection": (create_selection, []),
        "/clear_selection":  (clear_selection, []),
    }


_ROUTES = _route_table()


class Handler(BaseHTTPRequestHandler):
    def log_request(self, code="-", size="-"):
        pass

    def log_message(self, fmt, *args):
        sys.stderr.write("[bridge http] " + (fmt % args) + "\n")

    def _send_json(self, code, payload):
        body = json.dumps(payload, default=repr).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n == 0:
            return {}
        raw = self.rfile.read(n)
        return json.loads(raw)

    def do_GET(self):
        if self.path == "/ping":
            return self._send_json(200, {
                "ok": True,
                "pid": os.getpid(),
                "project_root": BASE_DIR,
            })
        return self._send_json(404, {"error": "not found", "path": self.path})

    def do_POST(self):
        try:
            body = self._read_json()

            # Special cases
            if self.path == "/ping":
                # Include project_root so the agent can discover where
                # its relative paths will anchor. The agent calls ping
                # at the start of a turn anyway; piggy-backing on that
                # avoids needing a separate "where am I?" tool.
                result = run_on_gui(lambda: {
                    "ok": True,
                    "project_root": BASE_DIR,
                })
                return self._send_json(200, result)
            if self.path == "/exec":
                if "code" not in body:
                    return self._send_json(400, {"error": "missing 'code'"})
                code = body["code"]
                result = run_on_gui(lambda: exec_script(code), timeout=600.0)
                return self._send_json(200, result)

            # Standard dispatch
            entry = _ROUTES.get(self.path)
            if entry is None:
                return self._send_json(404, {"error": "not found", "path": self.path})

            func, required = entry
            for key in required:
                if key not in body and key.rstrip("_") not in body:
                    return self._send_json(400, {"error": f"missing '{key.rstrip('_')}'"})

            # Normalize: body keys may use trailing-underscore'd names (range_, type_)
            # to avoid Python keyword clashes; clients pass them without underscore.
            kwargs = {}
            for key, val in body.items():
                if key in ("range", "type"):
                    kwargs[key + "_"] = val
                else:
                    kwargs[key] = val

            result = run_on_gui(lambda: func(**kwargs))
            return self._send_json(200, result)
        except Exception as e:
            return self._send_json(500, {
                "error": str(e),
                "type": type(e).__name__,
                "trace": traceback.format_exc(),
            })


def _start_http_server():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True, name="bridge-http")
    t.start()
    print(f"[bridge] HTTP server on http://127.0.0.1:{PORT}", flush=True)
    return server


def _install_timer():
    global _timer_iren, _timer_observer_id, _timer_id
    from paraview.simple import GetActiveView
    view = GetActiveView()
    if view is None:
        raise RuntimeError("no active view; cannot install drain timer")
    client_view = view.SMProxy.GetClientSideObject()
    iren = None
    if hasattr(client_view, "GetInteractor"):
        iren = client_view.GetInteractor()
    if iren is None:
        rw = client_view.GetRenderWindow()
        iren = rw.GetInteractor() if rw is not None else None
    if iren is None:
        raise RuntimeError("no interactor on active render window")
    _timer_iren = iren
    _timer_observer_id = iren.AddObserver(vtkCommand.TimerEvent, _drain_queue)
    _timer_id = iren.CreateRepeatingTimer(20)
    print("[bridge] VTK repeating timer installed on interactor", flush=True)


def _maybe_load_case():
    case_path = os.environ.get("PV_CASE_PATH")
    if not case_path:
        print("[bridge] PV_CASE_PATH not set; skipping auto-load", flush=True)
        return
    if not os.path.exists(case_path):
        print(f"[bridge] PV_CASE_PATH not found: {case_path}", flush=True)
        return
    try:
        info = load_dataset(case_path)
        print(f"[bridge] loaded {case_path}: {info}", flush=True)
    except Exception as e:
        print(f"[bridge] load failed: {e}", flush=True)
        traceback.print_exc()


_install_timer()
_start_http_server()
_task_queue.put(_maybe_load_case)
