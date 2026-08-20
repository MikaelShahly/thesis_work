"""Dev entrypoint: `python main.py` boots the FastAPI app with reload."""

import uvicorn

from src.config import HOST, PORT


if __name__ == "__main__":
    # Scope the reloader to backend source. Without reload_dirs,
    # uvicorn watches the whole repo for *.py changes — including
    # projects/, the agent's working dir. An agent Edit/Write of a .py
    # file there would then restart the server mid-turn, killing the
    # SSE stream and leaving the UI stuck "working" with a dead
    # interrupt button.
    uvicorn.run(
        "src.api.app:app",
        host=HOST,
        port=PORT,
        reload=True,
        reload_dirs=["src"],
    )
