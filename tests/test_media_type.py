"""Unit tests for media_type inference, settings batch sizes, and transfer pending filters."""

from __future__ import annotations

import os

import pytest

from q2google.config import Q2GoogleSettings, get_settings
from q2google.stages.transfer import TransferStage
from q2google.state.base import ItemState, media_type_for_filename, new_session


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("GX010001.JPG", "photo"),
        ("GX010001.jpg", "photo"),
        ("frame.PNG", "photo"),
        ("clip.MP4", "video"),
        ("clip.mp4", "video"),
        ("slowmo.MOV", "video"),
        ("proxy.LRV", "video"),
        ("sphere.360", "video"),
        ("unknown.bin", "photo"),
    ],
)
def test_media_type_for_filename(file_name: str, expected: str) -> None:
    assert media_type_for_filename(file_name) == expected


def test_item_state_derives_media_type_from_filename() -> None:
    photo = ItemState(file_name="still.JPG")
    video = ItemState(file_name="clip.mp4")
    assert photo.media_type == "photo"
    assert video.media_type == "video"


def test_item_state_media_type_roundtrip_and_legacy() -> None:
    video = ItemState(file_name="a.mp4", media_type="video", download_url="https://example.invalid/a.mp4")
    restored = ItemState.from_dict(video.to_dict())
    assert restored.media_type == "video"

    legacy = ItemState.from_dict(
        {
            "file_name": "b.MP4",
            "discovery_status": "completed",
            "transfer_status": "pending",
        }
    )
    assert legacy.media_type == "video"

    legacy_photo = ItemState.from_dict({"file_name": "c.JPG"})
    assert legacy_photo.media_type == "photo"


def test_settings_batch_size_for(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("GP_ACCESS_TOKEN", "test-token")
    monkeypatch.delenv("Q2GOOGLE_GOPRO_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("Q2GOOGLE_SYNC_PHOTO_BATCH_SIZE", "25")
    monkeypatch.setenv("Q2GOOGLE_SYNC_VIDEO_BATCH_SIZE", "3")
    try:
        settings = Q2GoogleSettings()
        assert settings.batch_size_for("photo") == 25
        assert settings.batch_size_for("video") == 3
    finally:
        get_settings.cache_clear()


def test_settings_batch_size_for_rejects_unknown() -> None:
    os.environ.setdefault("GP_ACCESS_TOKEN", "test-token")
    settings = Q2GoogleSettings(
        gopro_access_token="test-token",
        sync_photo_batch_size=10,
        sync_video_batch_size=2,
    )
    with pytest.raises(ValueError, match="Unsupported media_type"):
        settings.batch_size_for("audio")  # type: ignore[arg-type]


def test_pending_file_names_filters_by_media_type() -> None:
    state = new_session("s1", start_date_iso="2026-01-01", end_date_iso="2026-01-02", batch_size=10)
    state.items["a.jpg"] = ItemState(
        file_name="a.jpg",
        download_url="https://example.invalid/a.jpg",
        discovery_status="completed",
        transfer_status="pending",
    )
    state.items["b.mp4"] = ItemState(
        file_name="b.mp4",
        download_url="https://example.invalid/b.mp4",
        discovery_status="completed",
        transfer_status="pending",
    )
    state.items["c.mp4"] = ItemState(
        file_name="c.mp4",
        download_url="https://example.invalid/c.mp4",
        discovery_status="completed",
        transfer_status="completed",
    )
    state.items["d.jpg"] = ItemState(
        file_name="d.jpg",
        discovery_status="pending",
        transfer_status="pending",
    )

    assert TransferStage.pending_file_names(state) == ["a.jpg", "b.mp4"]
    assert TransferStage.pending_file_names(state, media_type="photo") == ["a.jpg"]
    assert TransferStage.pending_file_names(state, media_type="video") == ["b.mp4"]
