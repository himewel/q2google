"""Unit tests for :class:`~q2google.state.local.JsonFileBackend`.

These tests avoid GoPro and Google network I/O.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from q2google.state.base import ItemState, new_session
from q2google.state.local import JsonFileBackend


def test_json_file_backend_save_load_roundtrip() -> None:
    """Checks that save/load preserves item URLs for a minimal session."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        backend = JsonFileBackend(root)
        sid = "test-session-1"

        state = new_session(
            sid,
            start_date_iso="2026-01-01",
            end_date_iso="2026-01-02",
            batch_size=50,
        )
        state.items["a.mp4"] = ItemState(
            file_name="a.mp4",
            download_url="https://example.invalid/a.mp4",
            discovery_status="completed",
            transfer_status="pending",
        )
        backend.save(state)

        loaded = backend.load(sid)
        assert loaded is not None
        assert loaded.items["a.mp4"].download_url.endswith("a.mp4")


def test_json_file_backend_resume_failed_transfer() -> None:
    """Checks that a failed transfer status round-trips through persistence."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        backend = JsonFileBackend(root)
        sid = "test-session-2"

        state = new_session(
            sid,
            start_date_iso="2026-01-01",
            end_date_iso="2026-01-02",
            batch_size=50,
        )
        state.items["a.mp4"] = ItemState(
            file_name="a.mp4",
            download_url="https://example.invalid/a.mp4",
            discovery_status="completed",
            transfer_status="pending",
        )
        backend.save(state)

        loaded = backend.load(sid)
        assert loaded is not None
        loaded.items["a.mp4"].transfer_status = "failed"
        loaded.items["a.mp4"].errors["transfer"] = {
            "error_type": "RuntimeError",
            "message": "boom",
            "attempt": 1,
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        backend.save(loaded)

        again = backend.load(sid)
        assert again is not None
        assert again.items["a.mp4"].transfer_status == "failed"
