"""Pydantic models and enums for Google Photos Library API payloads and upload headers.

Types mirror JSON resources and resumable-upload header fields.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PhotosScopes(str, Enum):
    """OAuth 2.0 scope URLs accepted by the Google Photos Library API.

    Examples:
        >>> PhotosScopes.LIBRARY_APPENDONLY
    """

    LIBRARY_APPENDONLY = "https://www.googleapis.com/auth/photoslibrary.appendonly"
    """Create albums and upload media; cannot read or delete unrelated library content."""

    LIBRARY_READONLY_APP_CREATED = "https://www.googleapis.com/auth/photoslibrary.readonly.appcreateddata"
    """Read media and albums created by this app only."""

    LIBRARY_EDIT_APP_CREATED = "https://www.googleapis.com/auth/photoslibrary.edit.appcreateddata"
    """Edit and delete media and albums created by this app."""


class ResumableUploadSession(BaseModel):
    """State parsed from Google resumable upload response headers (and optional body token).

    Examples:
        >>> ResumableUploadSession.model_validate(
        ...     {
        ...         "X-Goog-Upload-Status": "active",
        ...         "X-GUploader-UploadID": "upload-id",
        ...         "Date": "Mon, 01 Jan 2024 00:00:00 GMT",
        ...     }
        ... )
    """

    upload_url: str | None = Field(alias="X-Goog-Upload-URL", default=None)
    """URL to POST the next chunk or query, when provided by the server."""

    granularity: int | None = Field(
        alias="X-Goog-Upload-Chunk-Granularity",
        default=None,
    )
    """Preferred chunk size in bytes, if the server advertises one."""

    status: str = Field(alias="X-Goog-Upload-Status")
    """Upload lifecycle status string from ``X-Goog-Upload-Status``."""

    upload_id: str = Field(alias="X-GUploader-UploadID")
    """Server upload identifier from ``X-GUploader-UploadID``."""

    date: datetime = Field(alias="Date")
    """Response ``Date`` header value, parsed to UTC-aware naive or as returned."""

    upload_token: str | None = None
    """Raw upload token from the response body when the upload is complete."""

    @field_validator("date", mode="before")
    def parse_date(cls, v: str) -> datetime:
        """Parse RFC 2822-style date strings from upload responses.

        Args:
            v: Date header value as returned by Google.

        Returns:
            Parsed datetime.
        """
        return datetime.strptime(v, "%a, %d %b %Y %H:%M:%S %Z")


class SimpleMediaItem(BaseModel):
    """Minimal media reference for batch create (upload token plus optional filename).

    Examples:
        >>> SimpleMediaItem(uploadToken="token", fileName="photo.jpg")
    """

    fileName: str | None = None
    """Suggested filename for the created item."""

    uploadToken: str
    """Upload token obtained after a successful resumable upload."""


class NewMediaItem(BaseModel):
    """One new media item entry inside a batch create request.

    Examples:
        >>> NewMediaItem(simpleMediaItem=SimpleMediaItem(uploadToken="tok"))
    """

    description: str | None = None
    """Optional description stored with the media item."""

    simpleMediaItem: SimpleMediaItem
    """Upload token and optional filename for this item."""


class MediaItemBatchCreateRequest(BaseModel):
    """Request body for ``mediaItems:batchCreate``.

    Examples:
        >>> MediaItemBatchCreateRequest(
        ...     newMediaItems=[NewMediaItem(simpleMediaItem=SimpleMediaItem(uploadToken="t"))],
        ... )
    """

    albumId: str | None = None
    """If set, add created items to this album id."""

    newMediaItems: list[NewMediaItem]
    """Items to create from prior upload tokens."""


class Status(BaseModel):
    """Per-item status in a batch create response.

    Examples:
        >>> Status(message="Success")
    """

    code: int | None = None
    """Optional numeric status code from the API."""

    message: str
    """Human-readable status or error message."""

    details: list[str] | None = None
    """Optional list of additional detail strings."""


class MediaMetadata(BaseModel):
    """Subset of ``mediaMetadata`` returned on a media item; extra keys are preserved.

    Examples:
        >>> MediaMetadata(creationTime="2024-01-01T00:00:00Z", width=1920, height=1080)
    """

    model_config = ConfigDict(extra="allow")

    creationTime: str | None = None
    """ISO 8601 creation time when provided."""

    width: int | None = None
    """Pixel width when provided."""

    height: int | None = None
    """Pixel height when provided."""


class MediaItem(BaseModel):
    """A media item resource as returned by the Library API.

    Examples:
        >>> MediaItem(
        ...     id="ABC",
        ...     productUrl="https://photos.google.com/lr/photo/ABC",
        ...     mimeType="image/jpeg",
        ... )
    """

    id: str
    """Opaque media item identifier."""

    description: str | None = None
    """User-visible description when present."""

    productUrl: str
    """URL to open the item in Google Photos."""

    baseUrl: str | None = None
    """Base URL for requesting image bytes with size parameters, when present."""

    mimeType: str
    """MIME type of the primary asset."""

    mediaMetadata: MediaMetadata | None = None
    """Dimensions, timestamps, and other metadata."""

    filename: str | None = None
    """Filename when available."""


class NewMediaItemResult(BaseModel):
    """Outcome for one entry in a ``mediaItems:batchCreate`` response.

    Examples:
        >>> NewMediaItemResult(
        ...     uploadToken="t",
        ...     status=Status(message="Success"),
        ... )
    """

    uploadToken: str
    """Upload token this result corresponds to."""

    status: Status
    """Success or error details for this token."""

    mediaItem: MediaItem | None = None
    """Created media item when the call succeeded for this token."""


class MediaItemBatchCreateResponse(BaseModel):
    """Response body from ``mediaItems:batchCreate``.

    Examples:
        >>> MediaItemBatchCreateResponse(newMediaItemResults=[])
    """

    newMediaItemResults: list[NewMediaItemResult]
    """Parallel list of results aligned with the request ``newMediaItems`` order."""
