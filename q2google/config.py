"""Runtime configuration for q2google.

Loads settings from environment variables (prefix ``Q2GOOGLE_``), optional ``.env`` in the
working directory, and defaults suitable for local CLI use.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from q2google.state.base import MediaType

#: Maximum ``newMediaItems`` per ``mediaItems:batchCreate`` request (Google Photos Library API).
PHOTOS_LIBRARY_BATCH_MAX = 50

_DEFAULT_DOWNLOAD_CHUNK_BYTES = 1024 * 1024
_DEFAULT_SYNC_PHOTO_BATCH_SIZE = 50
_DEFAULT_SYNC_VIDEO_BATCH_SIZE = 10


class Q2GoogleSettings(BaseSettings):
    """Application settings merged from defaults, ``.env``, and ``Q2GOOGLE_*`` environment variables.

    Environment variables are uppercase with prefix ``Q2GOOGLE_``; for example,
    ``state_dir`` maps to ``Q2GOOGLE_STATE_DIR``. Unknown env keys are ignored.

    Attributes:
        credentials_path: Path to the OAuth client secrets JSON (installed application).
        token_path: Path where the authorized user refresh token is stored.
        state_dir: Directory containing one JSON file per sync session (used when ``state_uri`` is unset).
        state_uri: Backend URI whose scheme selects the storage engine; overrides ``state_dir`` when set.
        session_id: Optional default session identifier when the CLI omits ``--session-id``.
        gopro_access_token: GoPro cloud access token for discovery and CDN URL resolution.
        gopro_max_items: Upper bound passed to GoPro cloud listing.
        gopro_prefer_height: Preferred pixel height when resolving GoPro CDN assets.
        google_photos_timeout_seconds: Total timeout per Library API HTTP request.
        chunk_granularity_multiplier: Multiplier for resumable upload chunk size vs API granularity.
        sync_batch_size: Legacy transfer batch size. When set (env/kwargs) without photo/video
            overrides, both :attr:`sync_photo_batch_size` and :attr:`sync_video_batch_size` inherit it.
        sync_photo_batch_size: Transfer batch size for photo items.
        sync_video_batch_size: Transfer batch size for video items (typically smaller).
        photos_library_batch_size: Number of items per ``batchCreate`` call (at most 50).
        fail_fast: Whether to stop the pipeline after the first persisted error.
        download_chunk_size_bytes: Read/write chunk size for CDN streaming downloads.
        cdn_download_sock_connect_seconds: Connect-phase timeout for CDN ``aiohttp`` sessions.
        temp_dir_prefix: Prefix for temporary directories used during transfer.
        log_level: Default logging level name for the CLI.
    """

    model_config = SettingsConfigDict(
        env_prefix="Q2GOOGLE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    credentials_path: Path = Field(
        default=Path("client_secret.json"),
        description="Google OAuth client secrets JSON (installed app).",
    )
    token_path: Path = Field(
        default=Path("token.json"),
        description="Authorized user token persistence path.",
    )
    state_dir: Path = Field(
        default=Path(".q2google_sessions"),
        description="JSON session state directory for resume checkpoints (used when state_uri is not set).",
    )
    state_uri: str | None = Field(
        default=None,
        description=(
            "Backend URI that determines the storage engine. "
            "The URI scheme selects the backend: ``mongodb://host:port/db`` uses MongoBackend; "
            "absent falls back to JsonFileBackend(state_dir). "
            "Example: ``mongodb://localhost:27017/q2google``."
        ),
    )
    session_id: str | None = Field(
        default=None,
        description="Default session id when not passed explicitly (e.g. CLI --session-id).",
    )
    gopro_access_token: str = Field(
        description="GoPro cloud access token (env: ``GP_ACCESS_TOKEN`` or ``Q2GOOGLE_GOPRO_ACCESS_TOKEN``).",
        validation_alias=AliasChoices("GP_ACCESS_TOKEN", "Q2GOOGLE_GOPRO_ACCESS_TOKEN"),
    )

    gopro_max_items: int = Field(default=2000, ge=1, description="Cap for list_media_items.")
    gopro_prefer_height: int = Field(
        default=2704,
        ge=1,
        description="Preferred asset height when resolving GoPro download URLs.",
    )

    google_photos_timeout_seconds: float = Field(
        default=600.0,
        gt=0,
        description="Per-request timeout for Google Photos Library API (seconds).",
    )
    chunk_granularity_multiplier: int = Field(
        default=4,
        ge=1,
        description="Resumable upload chunk size multiplier vs API granularity.",
    )

    sync_batch_size: int = Field(
        default=_DEFAULT_SYNC_PHOTO_BATCH_SIZE,
        ge=1,
        description=(
            "Legacy files-per-batch size. When explicitly set without photo/video sizes, "
            "both media types inherit this value."
        ),
    )
    sync_photo_batch_size: int = Field(
        default=_DEFAULT_SYNC_PHOTO_BATCH_SIZE,
        ge=1,
        description="Files per download/upload cycle for photo items (transfer stage).",
    )
    sync_video_batch_size: int = Field(
        default=_DEFAULT_SYNC_VIDEO_BATCH_SIZE,
        ge=1,
        description="Files per download/upload cycle for video items (transfer stage).",
    )
    photos_library_batch_size: int = Field(
        default=PHOTOS_LIBRARY_BATCH_MAX,
        ge=1,
        le=PHOTOS_LIBRARY_BATCH_MAX,
        description="Items per mediaItems:batchCreate request (max 50 per API).",
    )
    fail_fast: bool = Field(
        default=False,
        description="Abort on first item/batch error after persisting failure state.",
    )

    download_chunk_size_bytes: int = Field(
        default=_DEFAULT_DOWNLOAD_CHUNK_BYTES,
        ge=1024,
        description="Stream read/write chunk size for GoPro CDN downloads.",
    )
    cdn_download_sock_connect_seconds: float | None = Field(
        default=30.0,
        gt=0,
        description="aiohttp sock_connect timeout for CDN GET (total timeout unlimited).",
    )
    temp_dir_prefix: str = Field(
        default="q2google_",
        description="Prefix for transfer-stage TemporaryDirectory names.",
    )

    log_level: str = Field(default="INFO", description="Logging level name (DEBUG, INFO, …).")

    @model_validator(mode="after")
    def _apply_legacy_sync_batch_size(self) -> Self:
        """Copy legacy ``sync_batch_size`` onto photo/video sizes when they were not set."""
        fields_set = self.model_fields_set
        if "sync_batch_size" not in fields_set:
            return self
        if "sync_photo_batch_size" not in fields_set:
            self.sync_photo_batch_size = self.sync_batch_size
        if "sync_video_batch_size" not in fields_set:
            self.sync_video_batch_size = self.sync_batch_size
        return self

    def batch_size_for(self, media_type: MediaType) -> int:
        """Return the transfer batch size configured for ``media_type``.

        Args:
            media_type: ``photo`` or ``video``.

        Returns:
            :attr:`sync_photo_batch_size` or :attr:`sync_video_batch_size`.

        Raises:
            ValueError: When ``media_type`` is not ``photo`` or ``video``.
        """
        if media_type == "photo":
            return self.sync_photo_batch_size
        if media_type == "video":
            return self.sync_video_batch_size
        raise ValueError(f"Unsupported media_type: {media_type!r}")


@lru_cache
def get_settings() -> Q2GoogleSettings:
    """Return the process-wide settings singleton.

    The result is memoized. Call ``get_settings.cache_clear()`` before constructing a new
    ``Q2GoogleSettings`` instance when tests mutate the environment.

    Returns:
        Parsed :class:`Q2GoogleSettings` for the current process.
    """
    return Q2GoogleSettings()


#: Default CDN download chunk size in bytes; mirrors :attr:`Q2GoogleSettings.download_chunk_size_bytes`.
DEFAULT_DOWNLOAD_CHUNK_SIZE = _DEFAULT_DOWNLOAD_CHUNK_BYTES

__all__ = [
    "DEFAULT_DOWNLOAD_CHUNK_SIZE",
    "PHOTOS_LIBRARY_BATCH_MAX",
    "Q2GoogleSettings",
    "get_settings",
]
