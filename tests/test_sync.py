"""JsonFileBackend-specific tests.

Protocol-compliance tests that run for all backends live in ``test_state_backends.py``.
This module covers behaviour unique to :class:`~q2google.state.local.JsonFileBackend`:
legacy flat-file format compatibility and directory-tree layout details.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from q2google.state.base import ItemState, new_session
from q2google.state.local import JsonFileBackend


def test_legacy_flat_file_is_readable() -> None:
    """load() transparently reads sessions written in the old single-file format."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sid = "legacy-session"
        state = new_session(sid, start_date_iso="2026-01-01", end_date_iso="2026-01-02", batch_size=50)
        state.items["v.mp4"] = ItemState(
            file_name="v.mp4",
            download_url="https://example.invalid/v.mp4",
            discovery_status="completed",
        )

        legacy_path = root / f"{sid}.json"
        legacy_path.write_text(json.dumps(state.to_dict()), encoding="utf-8")

        backend = JsonFileBackend(root)
        loaded = backend.load(sid)
        assert loaded is not None
        assert loaded.items["v.mp4"].download_url == "https://example.invalid/v.mp4"


def test_directory_tree_layout() -> None:
    """save() writes meta.json, items/, and batches/ under the session directory."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sid = "layout-session"
        backend = JsonFileBackend(root)

        state = new_session(sid, start_date_iso="2026-01-01", end_date_iso="2026-01-02", batch_size=50)
        state.items["clip.mp4"] = ItemState(file_name="clip.mp4", discovery_status="completed")
        backend.save(state)

        session_dir = root / sid
        assert (session_dir / "meta.json").is_file()
        assert (session_dir / "items" / "clip.mp4.json").is_file()
