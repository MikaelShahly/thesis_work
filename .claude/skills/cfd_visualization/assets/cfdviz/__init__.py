"""cfdviz — a small toolkit for fantastic, consistent CFD visualizations.

Three concerns, three modules:

    style   palette, colormaps, matplotlib rcParams, Plotly template (report-matched)
    render  pyvista off-screen rendering: themed Plotter, scalar bars, camera presets
    charts  2D charts (matplotlib static + Plotly interactive) and OpenFOAM log parsers

Typical use:

    import sys; sys.path.insert(0, "<skill>/assets")
    from cfdviz import render, charts, style
    from cfdviz.render import field_slice, open_foam

The modules are independent — import only what a task needs. `render` requires
pyvista/vtk; `charts` requires matplotlib (and optionally plotly); `style` is pure.
"""

from . import style  # noqa: F401

__all__ = ["style", "render", "charts", "maps"]
__version__ = "1.0"
