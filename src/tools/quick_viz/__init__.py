"""quick_viz MCP tool: one-shot headless ParaView render.

Like ``web_fetch``, the tool object is built per turn (bound to the
project dir so pvbatch runs with the right cwd), so this package exports
the SERVER NAME, the TOOL NAME, and the ``make_quick_viz`` factory —
not a static tool object. ``build_tooling`` constructs the bound object
when a ``project_dir`` is supplied.
"""

from src.tools.quick_viz.tool import QUICK_VIZ_TOOL, make_quick_viz

QUICK_VIZ_MCP_SERVER_NAME = "quick_viz"

__all__ = ["QUICK_VIZ_MCP_SERVER_NAME", "QUICK_VIZ_TOOL", "make_quick_viz"]
