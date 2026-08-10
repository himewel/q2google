"""Unit tests for media_type inference, settings batch sizes, and transfer pending filters."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from q2google.config import Q2GoogleSettings, get_settings
from q2google.stages.transfer import TransferStage
from q2google.state.base import ItemState, media_type_for_filename, new_session
from q2google.state.local import JsonFileBackend
from q2google.sync import GoProToPhotosSync


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


def test_legacy_sync_batch_size_seeds_photo_and_video(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("GP_ACCESS_TOKEN", "test-token")
    monkeypatch.delenv("Q2GOOGLE_GOPRO_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("Q2GOOGLE_SYNC_BATCH_SIZE", "7")
    monkeypatch.delenv("Q2GOOGLE_SYNC_PHOTO_BATCH_SIZE", raising=False)
    monkeypatch.delenv("Q2GOOGLE_SYNC_VIDEO_BATCH_SIZE", raising=False)
    try:
        settings = Q2GoogleSettings()
        assert settings.batch_size_for("photo") == 7
        assert settings.batch_size_for("video") == 7
    finally:
        get_settings.cache_clear()


def test_photo_video_env_wins_over_legacy_sync_batch_size(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("GP_ACCESS_TOKEN", "test-token")
    monkeypatch.delenv("Q2GOOGLE_GOPRO_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("Q2GOOGLE_SYNC_BATCH_SIZE", "7")
    monkeypatch.setenv("Q2GOOGLE_SYNC_PHOTO_BATCH_SIZE", "25")
    monkeypatch.setenv("Q2GOOGLE_SYNC_VIDEO_BATCH_SIZE", "3")
    try:
        settings = Q2GoogleSettings()
        assert settings.batch_size_for("photo") == 25
        assert settings.batch_size_for("video") == 3
    finally:
        get_settings.cache_clear()


def test_settings_batch_size_for_rejects_unknown() -> None:
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


def test_json_backend_infers_media_type_for_legacy_item(tmp_path: Path) -> None:
    backend = JsonFileBackend(tmp_path)
    sid = "legacy-media-type"
    state = new_session(sid, start_date_iso="2026-01-01", end_date_iso="2026-01-02", batch_size=10)
    state.items["clip.mp4"] = ItemState(
        file_name="clip.mp4",
        download_url="https://example.invalid/clip.mp4",
        discovery_status="completed",
        transfer_status="pending",
    )
    backend.save(state)

    item_path = tmp_path / sid / "items" / "clip.mp4.json"
    raw = json.loads(item_path.read_text())
    del raw["media_type"]
    item_path.write_text(json.dumps(raw))

    loaded = backend.load(sid)
    assert loaded is not None
    assert loaded.items["clip.mp4"].media_type == "video"


@pytest.mark.asyncio
async def test_transfer_run_batches_photos_then_videos_with_distinct_sizes() -> None:
    state = new_session("t1", start_date_iso="2026-01-01", end_date_iso="2026-01-02", batch_size=50)
    for name in ("a.jpg", "b.jpg", "c.jpg", "d.mp4", "e.mp4"):
        state.items[name] = ItemState(
            file_name=name,
            download_url=f"https://example.invalid/{name}",
            discovery_status="completed",
            transfer_status="pending",
        )

    download_batches: list[list[str]] = []

    async def fake_download(self, download_client, tmp_path, batch):
        names = [fn for fn, _ in batch]
        download_batches.append(names)
        out = []
        for fn, _asset in batch:
            path = tmp_path / Path(fn).name
            path.write_bytes(b"x")
            out.append((fn, path))
        return out

    photos = MagicMock()
    photos.upload_file_path = AsyncMock(return_value=SimpleNamespace(upload_token="tok"))

    stage = TransferStage(
        photos=photos,
        persist=AsyncMock(),
        download_chunk_size=1024,
        cdn_sock_connect_seconds=1.0,
        temp_dir_prefix="q2google_test_",
    )

    original = TransferStage._download_chunk
    try:
        TransferStage._download_chunk = fake_download  # type: ignore[method-assign]
        await stage.run(state, photo_batch_size=2, video_batch_size=1, fail_fast=True)
    finally:
        TransferStage._download_chunk = original  # type: ignore[method-assign]

    assert download_batches == [["a.jpg", "b.jpg"], ["c.jpg"], ["d.mp4"], ["e.mp4"]]
    assert all(state.items[n].transfer_status == "completed" for n in state.items)


@pytest.mark.asyncio
async def test_sync_new_session_uses_settings_per_type_batch_sizes(tmp_path: Path) -> None:
    backend = JsonFileBackend(tmp_path)
    settings = Q2GoogleSettings(
        gopro_access_token="test-token",
        sync_photo_batch_size=11,
        sync_video_batch_size=2,
    )
    syncer = GoProToPhotosSync(
        gopro=MagicMock(),
        photos=MagicMock(),
        state_backend=backend,
        settings=settings,
    )
    captured: dict[str, int] = {}

    async def fake_discovery(state):
        state.stages["discovery"] = "completed"

    async def fake_transfer(state, **kwargs):
        captured["photo_batch_size"] = kwargs["photo_batch_size"]
        captured["video_batch_size"] = kwargs["video_batch_size"]
        state.stages["transfer"] = "completed"

    async def fake_create(state, **kwargs):
        state.stages["create"] = "completed"
        return []

    syncer._discovery.run = fake_discovery  # type: ignore[method-assign]
    syncer._transfer.run = fake_transfer  # type: ignore[method-assign]
    syncer._create.run = fake_create  # type: ignore[method-assign]

    await syncer.sync_date_range(
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 2, tzinfo=timezone.utc),
        session_id="new-session",
    )
    assert captured == {"photo_batch_size": 11, "video_batch_size": 2}
    loaded = backend.load("new-session")
    assert loaded is not None
    assert loaded.batch_size == 11


@pytest.mark.asyncio
async def test_sync_resume_uses_persisted_batch_size(tmp_path: Path) -> None:
    backend = JsonFileBackend(tmp_path)
    state = new_session(
        "resume-session",
        start_date_iso="2026-01-01T00:00:00+00:00",
        end_date_iso="2026-01-02T00:00:00+00:00",
        batch_size=7,
    )
    state.stages["discovery"] = "completed"
    backend.save(state)

    settings = Q2GoogleSettings(
        gopro_access_token="test-token",
        sync_photo_batch_size=50,
        sync_video_batch_size=10,
    )
    syncer = GoProToPhotosSync(
        gopro=MagicMock(),
        photos=MagicMock(),
        state_backend=backend,
        settings=settings,
    )
    captured: dict[str, int] = {}

    async def fake_discovery(state):
        return None

    async def fake_transfer(state, **kwargs):
        captured["photo_batch_size"] = kwargs["photo_batch_size"]
        captured["video_batch_size"] = kwargs["video_batch_size"]
        state.stages["transfer"] = "completed"

    async def fake_create(state, **kwargs):
        return []

    syncer._discovery.run = fake_discovery  # type: ignore[method-assign]
    syncer._transfer.run = fake_transfer  # type: ignore[method-assign]
    syncer._create.run = fake_create  # type: ignore[method-assign]

    await syncer.sync_date_range(
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 2, tzinfo=timezone.utc),
        session_id="resume-session",
    )
    assert captured == {"photo_batch_size": 7, "video_batch_size": 7}
