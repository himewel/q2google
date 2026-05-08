"""High-level Google Photos Library helpers built on :mod:`q2google.gphotos`.

Keeps direct ``gphotos`` imports localized to this module; callers should use
:class:`GooglePhotosClient`, :class:`GooglePhotoLibraryPort`, and re-exported types.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

import aiofiles
from q2google.config import PHOTOS_LIBRARY_BATCH_MAX
from q2google.gphotos.api import GooglePhotosAPI
from q2google.gphotos.auth import GooglePhotosOAuth
from q2google.gphotos.models import (
    MediaItemBatchCreateRequest,
    MediaItemBatchCreateResponse,
    NewMediaItem,
    PhotosScopes,
    ResumableUploadSession,
    SimpleMediaItem,
)

# Google Photos Library ``mediaItems:batchCreate`` allows at most 50 new items per request.
LIBRARY_BATCH_SIZE = PHOTOS_LIBRARY_BATCH_MAX

__all__ = [
    "LIBRARY_BATCH_SIZE",
    "GooglePhotoLibraryPort",
    "GooglePhotosAPI",
    "GooglePhotosClient",
    "GooglePhotosOAuth",
    "MediaItemBatchCreateRequest",
    "MediaItemBatchCreateResponse",
    "NewMediaItem",
    "PhotosScopes",
    "ResumableUploadSession",
    "SimpleMediaItem",
]


class GooglePhotoLibraryPort(Protocol):
    """Protocol for Library v1 resumable upload and ``mediaItems:batchCreate``.

    Implemented by :class:`~q2google.gphotos.api.GooglePhotosAPI` when used through
    :class:`GooglePhotosClient`.
    """

    async def init_upload_session(self, content_type: str, content_length: int) -> ResumableUploadSession:
        """Start a resumable upload and return the session (URL, token, chunk rules).

        Args:
            content_type: MIME type of the bytes that will be uploaded.
            content_length: Total size in bytes of the object to upload.

        Returns:
            Session descriptor including ``upload_url`` and chunk granularity.
        """
        ...

    async def upload_chunk(self, url: str, command: str, offset: int, content: bytes) -> ResumableUploadSession:
        """POST one chunk to the resumable upload URL.

        Args:
            url: ``upload_url`` from ``init_upload_session``.
            command: Upload command header value (for example ``"upload"`` or
                ``"upload, finalize"`` for the last chunk).
            offset: Byte offset of this chunk in the full object.
            content: Raw chunk bytes.

        Returns:
            Updated session state; the last call should include the upload token
            needed for ``batchCreate``.
        """
        ...

    async def create_media_item(self, media_item: MediaItemBatchCreateRequest) -> MediaItemBatchCreateResponse:
        """Create library media items from finalized upload tokens.

        Args:
            media_item: Batch request wrapping ``newMediaItems`` (up to API limit).

        Returns:
            API response with per-item status and identifiers.
        """
        ...


@dataclass
class GooglePhotosClient:
    """Stream local files via resumable upload and register them with ``batchCreate``.

    Attributes:
        api: Async port implementing upload session and batch create (typically ``GooglePhotosAPI``).
        chunk_granularity_multiplier: Factor applied to server ``granularity`` to size upload chunks;
            must be >= 1.
    """

    api: GooglePhotoLibraryPort
    chunk_granularity_multiplier: int = 4

    async def upload_file_path(
        self,
        file_name: str,
        path: Path,
    ) -> ResumableUploadSession:
        """Stream ``path`` to Google using resumable upload chunking.

        Chunk size is ``chunk_granularity_multiplier * granularity`` from the
        session when present; the final chunk may be smaller and uses the
        ``\"upload, finalize\"`` command.

        Args:
            file_name: Logical name used only for MIME guessing (not sent as path).
            path: Readable file on disk whose size defines ``Content-Length``.

        Returns:
            Final ``ResumableUploadSession`` after the finalize chunk (includes token).

        Raises:
            RuntimeError: If the session response omits chunk granularity metadata.
            ValueError: If ``chunk_granularity_multiplier`` is less than 1.
        """
        if self.chunk_granularity_multiplier < 1:
            msg = "chunk_granularity_multiplier must be >= 1"
            raise ValueError(msg)

        content_length = path.stat().st_size
        guessed = mimetypes.guess_type(file_name)[0]
        content_type = guessed if guessed is not None else "application/octet-stream"

        offset = 0
        upload = await self.api.init_upload_session(content_type, content_length)
        url = upload.upload_url
        if upload.granularity is None:
            msg = "Upload session missing X-Goog-Upload-Chunk-Granularity"
            raise RuntimeError(msg)

        granularity = self.chunk_granularity_multiplier * upload.granularity
        total_chunks = content_length // granularity

        async with aiofiles.open(path, "rb") as body:
            for _ in range(total_chunks):
                chunk = await body.read(granularity)
                await self.api.upload_chunk(url, "upload", offset, chunk)
                offset += len(chunk)

            chunk = await body.read()
            return await self.api.upload_chunk(url, "upload, finalize", offset, chunk)

    async def create_media_items(self, media_items: list[NewMediaItem]) -> list[MediaItemBatchCreateResponse]:
        """Call ``mediaItems:batchCreate`` in slices of at most ``LIBRARY_BATCH_SIZE`` items.

        Args:
            media_items: Full list of ``NewMediaItem`` to register in the library.

        Returns:
            One ``MediaItemBatchCreateResponse`` per HTTP batch, in order.
        """
        out: list[MediaItemBatchCreateResponse] = []
        for i in range(0, len(media_items), LIBRARY_BATCH_SIZE):
            batch_media_items = media_items[i : i + LIBRARY_BATCH_SIZE]
            media_item_request = MediaItemBatchCreateRequest(newMediaItems=batch_media_items)
            out.append(await self.api.create_media_item(media_item_request))
        return out

    async def create_media_items_from_upload_sessions(
        self,
        file_names: Sequence[str],
        sessions: Sequence[ResumableUploadSession],
    ) -> list[MediaItemBatchCreateResponse]:
        """Pair each local filename with its finalized upload session and call ``batchCreate``.

        ``file_names`` and ``sessions`` must align (same length, same order as uploads).

        Args:
            file_names: Display names for created media items.
            sessions: Finalized upload sessions whose ``upload_token`` matches each name.

        Returns:
            Batch create responses from ``create_media_items``.
        """
        media_items = [
            NewMediaItem(
                simpleMediaItem=SimpleMediaItem(
                    fileName=file_name,
                    uploadToken=session.upload_token,
                ),
            )
            for file_name, session in zip(file_names, sessions)
        ]
        return await self.create_media_items(media_items)
