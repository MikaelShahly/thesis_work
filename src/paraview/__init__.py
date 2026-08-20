"""ParaView runtime infrastructure.

`bridge.py` is loaded by `paraview --script=bridge.py`; it runs inside
the ParaView process and serves the HTTP-over-JSON verb surface on
http://127.0.0.1:8765. Not importable from the backend (depends on
`paraview.simple`, which only exists inside the ParaView interpreter).

`lifecycle.py` is the backend-side subprocess manager that launches
ParaView and tracks the live process.
"""
