"""Small utilities shared by discovery, transfer, and create stages."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Protocol, TypeVar

from q2google.gphotos.models import ResumableUploadSession
from q2google.state.base import ErrorRecord

T = TypeVar("T")


class CdnAsset(Protocol):
    """Minimal interface for CDN downloads that only require a URL."""

    url: str


def batched(items: Sequence[T], n: int) -> Iterator[list[T]]:
    """Yield contiguous slices from ``items`` with length at most ``n``.

    Args:
        items: Finite sequence to partition.
        n: Maximum slice length; the final slice may be shorter.

    Yields:
        Lists of consecutive elements from ``items``.
    """
    for i in range(0, len(items), n):
        yield list(items[i : i + n])


def restored_upload_session(upload_token: str) -> ResumableUploadSession:
    """Build a minimal :class:`~q2google.gphotos.models.ResumableUploadSession` for ``batchCreate``.

    Used when rehydrating state after transfer; headers are placeholders except for body token.

    Args:
        upload_token: Raw upload token returned by the resumable upload finalize response.

    Returns:
        Model instance acceptable by ``mediaItems:batchCreate`` pairing logic.
    """
    return ResumableUploadSession.model_validate(
        {
            "X-Goog-Upload-Status": "final",
            "X-GUploader-UploadID": "restored-from-session",
            "Date": "Thu, 01 Jan 1970 00:00:00 GMT",
            "upload_token": upload_token,
        }
    )


def error_record(exc: BaseException, attempt: int) -> ErrorRecord:
    """Create a structured :class:`~q2google.state.base.ErrorRecord` from an exception.

    Args:
        exc: The failure to record.
        attempt: Retry attempt number associated with this error.

    Returns:
        Typed dict suitable for storing on :class:`~q2google.state.base.ItemState` or batch state.
    """
    return {
        "error_type": type(exc).__name__,
        "message": str(exc) or repr(exc),
        "attempt": attempt,
        "updated_at": datetime.now().astimezone().isoformat(),
    }
