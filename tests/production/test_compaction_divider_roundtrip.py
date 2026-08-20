"""Compaction divider DB round-trip.

When the SDK auto-compacts context mid-turn, the route layer persists a
`compaction` message row carrying the pre/post token counts (see
`_persist_compaction` in src/api/routes.py). This test proves
`get_full_chat_history` synthesizes that row back into a
`{"type": "compaction", ...}` entry, in the correct chronological
position relative to the surrounding user / assistant turns — so the
divider reappears on reload exactly where it streamed in.

Mirrors the tmp-DB isolation used by the other persistence tests:
patch `config.DB_PATH`, reload `src.db`, init the schema.
"""

from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "agenticcfd.db"
    import src.config as config

    monkeypatch.setattr(config, "DB_PATH", db_path)

    import src.db as db_mod

    importlib.reload(db_mod)
    db_mod.init_db()
    return db_mod


def test_compaction_row_roundtrips_as_divider_entry(db):
    pid = db.create_project("Compaction test")
    sid = db.get_current_session(pid)["id"]

    # A turn in which the SDK compacted mid-stream: user prompt, then the
    # compaction boundary, then the assistant's (collapsed) turn.
    db.save_message(sid, "user", "build the mesh")
    db.save_message(sid, "compaction", json.dumps({
        "trigger": "auto",
        "pre_tokens": 167684,
        "post_tokens": 9557,
    }))
    db.save_assistant_turn(
        sid, "done", [{"kind": "text", "content": "done"}],
    )

    history = db.get_full_chat_history(pid)

    # Ordering survives: user message → compaction divider → assistant.
    assert [h.get("type") for h in history] == [
        "message", "compaction", "message",
    ]

    divider = history[1]
    assert divider["type"] == "compaction"
    assert divider["pre_tokens"] == 167684
    assert divider["post_tokens"] == 9557
    assert divider["trigger"] == "auto"

    # Surrounding turns are untouched.
    assert history[0]["role"] == "user"
    assert history[2]["role"] == "assistant"
    assert history[2]["segments"][0]["content"] == "done"


def test_malformed_compaction_content_degrades_to_bare_divider(db):
    """A non-JSON compaction row must not crash history rebuild — it
    should still surface as a divider, just without token counts."""
    pid = db.create_project("Compaction test 2")
    sid = db.get_current_session(pid)["id"]

    db.save_message(sid, "compaction", "not-json")

    history = db.get_full_chat_history(pid)
    assert [h.get("type") for h in history] == ["compaction"]
    assert "pre_tokens" not in history[0]
