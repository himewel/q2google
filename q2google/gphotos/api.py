"""Async client for Google Photos Library API v1 (uploads, batch create, media item lookup).

Use :class:`GooglePhotosAPI` only as an async context manager so an ``aiohttp`` session is opened
and closed correctly.
"""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Any

import aiohttp

from .auth import GooglePhotosOAuth
from .models import (
    MediaItemBatchCreateRequest,
    MediaItemBatchCreateResponse,
    ResumableUploadSession,
)


class GooglePhotosAPI:
    """Thin aiohttp wrapper around selected Google Photos Library v1 endpoints.

    Instantiate and use ``async with GooglePhotosAPI(...) as api`` to obtain a live session.
    HTTP error responses are surfaced via ``response.raise_for_status()`` (aiohttp client errors).
    """

    def __init__(self, credentials: GooglePhotosOAuth, timeout: float = 600.0) -> None:
        """Create a client; the HTTP session starts on async context enter.

        Args:
            credentials: OAuth credentials carrying a valid access token.
            timeout: Per-request total timeout in seconds. Each resumable chunk is one request;
                large uploads often need a generous value.
        """
        self._credentials = credentials
        self._token: str | None = None
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None

    @property
    def base_url(self) -> str:
        """Root URL for Library API v1 resources for this client."""
        return "https://photoslibrary.googleapis.com/v1/"

    async def __aenter__(self) -> GooglePhotosAPI:
        """Open the underlying ``aiohttp`` client session."""
        logging.info("Creating aiohttp client session")
        self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the client session.

        Args:
            exc_type: Exception type if the context exited due to an error, else ``None``.
            exc: Active exception instance when exiting with an error, else ``None``.
            tb: Traceback associated with ``exc``, if any.
        """
        if self._session is not None:
            await self._session.close()
            self._session = None

    def _get_session_or_raise(self) -> aiohttp.ClientSession:
        """Return the active session or fail if the context was not entered.

        Raises:
            RuntimeError: If used outside ``async with``.
        """
        if self._session is None:
            msg = "Use GooglePhotosAPI as an async context manager: async with GooglePhotosAPI() as api: ..."
            raise RuntimeError(msg)

        self._token = self._credentials.ensure_credentials().token
        return self._session

    def _auth_headers(self) -> dict[str, str]:
        """Headers including ``Authorization: Bearer …`` from credentials."""
        return {"Authorization": f"Bearer {self._token}"}

    async def init_upload_session(self, content_type: str, content_length: int) -> ResumableUploadSession:
        """Start a resumable upload; maps response headers to a session model.

        Args:
            content_type: MIME type of the file to upload.
            content_length: Total byte size of the file.

        Returns:
            Parsed upload session metadata from response headers.
        """
        logging.info("Initializing upload session")
        session = self._get_session_or_raise()
        headers = {
            **self._auth_headers(),
            "Content-Length": "0",
            "Content-Type": "application/octet-stream",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Content-Type": content_type,
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Raw-Size": str(content_length),
        }
        async with session.post(self.base_url + "uploads", headers=headers) as response:
            logging.info(response.headers)
            logging.info(await response.text())
            response.raise_for_status()
            return ResumableUploadSession.model_validate(dict(response.headers))

    async def upload_chunk(self, url: str, command: str, offset: int, content: bytes) -> ResumableUploadSession:
        """POST one chunk of a resumable upload.

        Args:
            url: Resumable upload URL from a prior session.
            command: Google resumable upload command (e.g. ``upload``, ``finalize``).
            offset: Byte offset for this chunk.
            content: Raw chunk bytes.

        Returns:
            Parsed session state; when the upload completes, ``upload_token`` may be set from
            the response body.
        """
        logging.info(f"Uploading chunk {offset} to {url}")
        session = self._get_session_or_raise()
        async with session.post(
            url,
            headers={
                **self._auth_headers(),
                "Content-Length": str(len(content)),
                "Content-Type": "application/octet-stream",
                "X-Goog-Upload-Command": command,
                "X-Goog-Upload-Offset": str(offset),
            },
            data=content,
        ) as response:
            logging.info(response.headers)
            body = await response.text()
            logging.info(body)
            response.raise_for_status()
            return ResumableUploadSession.model_validate(dict(response.headers, upload_token=body))

    async def query_upload_status(self, url: str) -> ResumableUploadSession:
        """Send an upload ``query`` command and return parsed header state.

        Args:
            url: Resumable upload URL to query.

        Returns:
            Parsed session metadata from response headers.
        """
        logging.info("Querying upload status")
        session = self._get_session_or_raise()
        async with session.post(
            url,
            headers={
                **self._auth_headers(),
                "Content-Length": str(0),
                "X-Goog-Upload-Command": "query",
            },
        ) as response:
            logging.info(response.headers)
            body = await response.text()
            logging.info(body)
            response.raise_for_status()
            return ResumableUploadSession.model_validate(dict(response.headers))

    async def create_media_item(self, media_item: MediaItemBatchCreateRequest) -> MediaItemBatchCreateResponse:
        """Call ``mediaItems:batchCreate`` with the given payload.

        Args:
            media_item: Batch create request body.

        Returns:
            API batch create response.
        """
        logging.info("Creating media item")
        session = self._get_session_or_raise()
        async with session.post(
            self.base_url + "mediaItems:batchCreate",
            headers={
                **self._auth_headers(),
                "Content-type": "application/json",
            },
            json=media_item.model_dump(),
        ) as response:
            logging.info(response.headers)
            response.raise_for_status()
            data = await response.json()
            logging.info(data)
            return MediaItemBatchCreateResponse.model_validate(data)

    async def get_media_item(self, media_item_id: str) -> dict[str, Any]:
        """GET a single media item by id (``mediaItems/{mediaItemId}``).

        Args:
            media_item_id: Library media item id.

        Returns:
            Parsed JSON object as returned by the API (shape matches the MediaItem resource).
        """
        logging.info(f"Getting media item with ID: {media_item_id}")
        session = self._get_session_or_raise()
        url = self.base_url + f"mediaItems/{media_item_id}"
        async with session.get(
            url,
            headers={
                **self._auth_headers(),
                "Content-type": "application/json",
            },
        ) as response:
            response.raise_for_status()
            data = await response.json()
            logging.info(data)
            return data
