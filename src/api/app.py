"""FastAPI application.

Lifespan strips any inherited ANTHROPIC_API_KEY from the process env
(this project authenticates via the Claude Code subscription only —
never via API key) and initialises the DB.
CORS is open to the Vite dev origin.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.agent import session_registry
from src.api.routes import router
from src.config import FRONTEND_ORIGIN
from src.db import init_db


# Strip the API key at import time as well as in lifespan, so it's gone
# before *anything* in this process can read it (including third-party
# imports that may snapshot env on load).
_STRIPPED_KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
for _k in _STRIPPED_KEYS:
    os.environ.pop(_k, None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Defence in depth — re-strip in case something else has set them.
    for k in _STRIPPED_KEYS:
        os.environ.pop(k, None)
    init_db()
    yield
    # Close every live SessionWorker (kills their subprocesses + any
    # background jobs) so the server doesn't leave orphaned processes.
    await session_registry.shutdown()


app = FastAPI(title="AgenticCFD (Agent SDK)", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_ORIGIN,
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
