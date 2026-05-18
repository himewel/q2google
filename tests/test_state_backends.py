"""Protocol-compliance tests for all :class:`~q2google.state.base.SyncStateBackend` implementations.

Each test in this module runs for every backend registered in the ``backend`` fixture
defined in ``conftest.py`` (currently ``json`` and ``mongo``).  Adding a new backend
to ``conftest.py`` automatically includes it in all tests here.
"""

from __future__ import annotations

from q2google.state.base import BatchState, ErrorRecord, ItemState, new_session


def test_save_load_roundtrip(backend) -> None:
    """save() followed by load() preserves all item fields."""
    sid = "test-roundtrip"
    state = new_session(sid, start_date_iso="2026-01-01", end_date_iso="2026-01-02", batch_size=50)
    state.items["a.mp4"] = ItemState(
        file_name="a.mp4",
        download_url="https://example.invalid/a.mp4",
        discovery_status="completed",
        transfer_status="pending",
    )
    backend.save(state)

    loaded = backend.load(sid)
    assert loaded is not None
    assert loaded.session_id == sid
    assert loaded.items["a.mp4"].download_url == "https://example.invalid/a.mp4"
    assert loaded.items["a.mp4"].discovery_status == "completed"
    assert loaded.items["a.mp4"].transfer_status == "pending"


def test_load_missing_session_returns_none(backend) -> None:
    """load() returns None for a session that was never saved."""
    assert backend.load("does-not-exist") is None


def test_resume_failed_transfer(backend) -> None:
    """A failed transfer status and error record round-trip through persistence."""
    sid = "test-resume-failed"
    state = new_session(sid, start_date_iso="2026-01-01", end_date_iso="2026-01-02", batch_size=50)
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
    loaded.items["a.mp4"].errors["transfer"] = ErrorRecord(
        error_type="RuntimeError",
        message="boom",
        attempt=1,
        updated_at="2026-01-01T00:00:00+00:00",
    )
    backend.save(loaded)

    again = backend.load(sid)
    assert again is not None
    assert again.items["a.mp4"].transfer_status == "failed"
    assert again.items["a.mp4"].errors["transfer"]["message"] == "boom"


def test_multiple_items_and_batches(backend) -> None:
    """Multiple items and batches are all preserved after a save/load cycle."""
    sid = "test-multi"
    state = new_session(sid, start_date_iso="2026-01-01", end_date_iso="2026-01-02", batch_size=2)

    for i in range(3):
        state.items[f"file{i}.mp4"] = ItemState(
            file_name=f"file{i}.mp4",
            discovery_status="completed",
            transfer_status="completed",
            create_status="pending",
        )

    state.batches["0"] = BatchState(batch_index=0, file_names=["file0.mp4", "file1.mp4"], status="completed")
    state.batches["1"] = BatchState(batch_index=1, file_names=["file2.mp4"], status="pending")
    backend.save(state)

    loaded = backend.load(sid)
    assert loaded is not None
    assert set(loaded.items) == {"file0.mp4", "file1.mp4", "file2.mp4"}
    assert loaded.batches["0"].status == "completed"
    assert loaded.batches["1"].status == "pending"
    assert loaded.batches["1"].file_names == ["file2.mp4"]


def test_overwrite_preserves_latest(backend) -> None:
    """Saving twice with updated state reflects the latest values on load."""
    sid = "test-overwrite"
    state = new_session(sid, start_date_iso="2026-01-01", end_date_iso="2026-01-02", batch_size=50)
    state.items["a.mp4"] = ItemState(file_name="a.mp4", transfer_status="pending")
    backend.save(state)

    state.items["a.mp4"].transfer_status = "completed"
    state.items["a.mp4"].upload_token = "tok_abc"
    backend.save(state)

    loaded = backend.load(sid)
    assert loaded is not None
    assert loaded.items["a.mp4"].transfer_status == "completed"
    assert loaded.items["a.mp4"].upload_token == "tok_abc"


def test_stage_status_roundtrip(backend) -> None:
    """Session-level stage statuses survive a save/load cycle."""
    sid = "test-stages"
    state = new_session(sid, start_date_iso="2026-01-01", end_date_iso="2026-01-02", batch_size=50)
    state.stages["discovery"] = "completed"
    state.stages["transfer"] = "running"
    backend.save(state)

    loaded = backend.load(sid)
    assert loaded is not None
    assert loaded.stages["discovery"] == "completed"
    assert loaded.stages["transfer"] == "running"
    assert loaded.stages["create"] == "pending"
