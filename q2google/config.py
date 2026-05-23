"""Runtime configuration for q2google.

Loads settings from environment variables (prefix ``Q2GOOGLE_``), optional ``.env`` in the
working directory, and defaults suitable for local CLI use.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Maximum ``newMediaItems`` per ``mediaItems:batchCreate`` request (Google Photos Library API).
PHOTOS_LIBRARY_BATCH_MAX = 50

_DEFAULT_DOWNLOAD_CHUNK_BYTES = 1024 * 1024


class Q2GoogleSettings(BaseSettings):
    """Application settings merged from defaults, ``.env``, and ``Q2GOOGLE_*`` environment variables.

    Environment variables are uppercase with prefix ``Q2GOOGLE_``; for example,
    ``state_dir`` maps to ``Q2GOOGLE_STATE_DIR``. Unknown env keys are ignored.

    Attributes:
        credentials_path: Path to the OAuth client secrets JSON (installed application).
        token_path: Path where the authorized user refresh token is stored.
        state_dir: Directory containing one JSON file per sync session.
        session_id: Optional default session identifier when the CLI omits ``--session-id``.
        gopro_access_token: GoPro cloud access token for discovery and CDN URL resolution.
        gopro_max_items: Upper bound passed to GoPro cloud listing.
        gopro_prefer_height: Preferred pixel height when resolving GoPro CDN assets.
        google_photos_timeout_seconds: Total timeout per Library API HTTP request.
        chunk_granularity_multiplier: Multiplier for resumable upload chunk size vs API granularity.
        sync_batch_size: Number of files per transfer batch for new sessions.
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
        description="JSON session state directory for resume checkpoints.",
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
        default=50,
        ge=1,
        description="Files per download/upload cycle for new sessions (transfer stage).",
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
