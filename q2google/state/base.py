"""Abstract persistence protocol and JSON-serializable session models.

Defines :class:`SyncStateBackend`, document types for staged sync, and helpers such as
:func:`new_session`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict

StageKey = Literal["discovery", "transfer", "create"]
StageStatus = Literal["pending", "running", "completed", "failed"]
ItemCreateStatus = Literal["pending", "running", "completed", "failed", "skipped"]
MediaType = Literal["photo", "video"]

#: Filename suffixes treated as video when inferring :attr:`ItemState.media_type`.
_VIDEO_SUFFIXES = frozenset(
    {
        ".mp4",
        ".mov",
        ".m4v",
        ".avi",
        ".mkv",
        ".webm",
        ".lrv",
        ".360",
    }
)


def media_type_for_filename(file_name: str) -> MediaType:
    """Infer ``photo`` vs ``video`` from a GoPro logical filename.

    Args:
        file_name: Filename or path whose suffix is inspected (case-insensitive).

    Returns:
        ``\"video\"`` for known video extensions; otherwise ``\"photo\"``.
    """
    suffix = Path(file_name).suffix.lower()
    if suffix in _VIDEO_SUFFIXES:
        return "video"
    return "photo"


class ErrorRecord(TypedDict, total=False):
    """Structured error payload stored on an item or batch.

    Attributes:
        error_type: Exception type name.
        message: Human-readable error message.
        attempt: Monotonic attempt counter for retries.
        updated_at: ISO 8601 timestamp when the record was written.
    """

    error_type: str
    message: str
    attempt: int
    updated_at: str


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ItemState:
    """Per-file progress within a sync session.

    Attributes:
        file_name: GoPro logical filename used as map key in :class:`SessionState`.
        media_id: Optional remote identifier when known.
        download_url: Resolved CDN URL after discovery.
        discovery_status: Lifecycle state for URL resolution.
        transfer_status: Lifecycle state for download + upload to Google.
        create_status: Lifecycle state for ``batchCreate``.
        upload_token: Finalized resumable upload token before library registration.
        media_type: ``photo`` or ``video``, derived from ``file_name`` when omitted.
        errors: Map of stage key (e.g. ``\"transfer\"``) to last :class:`ErrorRecord`.
    """

    file_name: str
    media_id: str | None = None
    download_url: str | None = None
    discovery_status: StageStatus = "pending"
    transfer_status: StageStatus = "pending"
    create_status: ItemCreateStatus = "pending"
    upload_token: str | None = None
    media_type: MediaType = field(default=None)  # type: ignore[assignment]
    errors: dict[str, ErrorRecord] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Derive :attr:`media_type` from :attr:`file_name` when not provided."""
        if self.media_type is None:
            self.media_type = media_type_for_filename(self.file_name)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this item to a plain dict suitable for JSON.

        Returns:
            JSON-compatible mapping for persistence layers.
        """
        return {
            "file_name": self.file_name,
            "media_id": self.media_id,
            "download_url": self.download_url,
            "discovery_status": self.discovery_status,
            "transfer_status": self.transfer_status,
            "create_status": self.create_status,
            "upload_token": self.upload_token,
            "media_type": self.media_type,
            "errors": dict(self.errors),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ItemState:
        """Deserialize from a dict produced by :meth:`to_dict` or legacy JSON.

        Args:
            data: Mapping with required ``file_name`` and optional status fields.

        Returns:
            Reconstructed :class:`ItemState`.

        Notes:
            Legacy documents without ``media_type`` infer it from ``file_name``.
        """
        file_name = str(data["file_name"])
        raw_media_type = data.get("media_type")
        media_type: MediaType | None
        if raw_media_type in ("photo", "video"):
            media_type = raw_media_type
        else:
            media_type = media_type_for_filename(file_name)
        return cls(
            file_name=file_name,
            media_id=data.get("media_id"),
            download_url=data.get("download_url"),
            discovery_status=data.get("discovery_status", "pending"),  # type: ignore[arg-type]
            transfer_status=data.get("transfer_status", "pending"),  # type: ignore[arg-type]
            create_status=data.get("create_status", "pending"),  # type: ignore[arg-type]
            upload_token=data.get("upload_token"),
            media_type=media_type,
            errors=dict(data.get("errors") or {}),
        )


@dataclass
class BatchState:
    """Tracks one ``mediaItems:batchCreate`` HTTP batch within the create stage.

    Attributes:
        batch_index: Zero-based index among create batches for this session.
        file_names: Filenames included in this batch (aligned with API order).
        status: Batch-level lifecycle state.
        responses_json: Optional serialized per-response JSON strings after success.
        error: Populated when the batch fails as a whole.
    """

    batch_index: int
    file_names: list[str]
    status: StageStatus = "pending"
    responses_json: list[str] | None = None
    error: ErrorRecord | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize this batch to a plain dict.

        Returns:
            JSON-compatible mapping.
        """
        return {
            "batch_index": self.batch_index,
            "file_names": list(self.file_names),
            "status": self.status,
            "responses_json": self.responses_json,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BatchState:
        """Deserialize batch metadata from persisted JSON.

        Args:
            data: Mapping with ``batch_index`` and optional nested fields.

        Returns:
            Reconstructed :class:`BatchState`.
        """
        return cls(
            batch_index=int(data["batch_index"]),
            file_names=list(data.get("file_names") or []),
            status=data.get("status", "pending"),  # type: ignore[arg-type]
            responses_json=data.get("responses_json"),
            error=data.get("error"),
        )


@dataclass
class SessionState:
    """Full persisted session for discovery → transfer → create.

    Attributes:
        schema_version: Document format version for migrations.
        session_id: Stable identifier used as storage key.
        created_at: ISO timestamp when the session was first created.
        updated_at: ISO timestamp last updated via :meth:`touch`.
        start_date_iso: Capture window start (ISO string).
        end_date_iso: Capture window end (ISO string).
        batch_size: Transfer-stage batch size chosen at session creation.
        stages: High-level stage keys mapped to coarse status.
        items: Filename-keyed :class:`ItemState` entries.
        batches: String-keyed batch index → :class:`BatchState` for create retries.
    """

    schema_version: int = 1
    session_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    start_date_iso: str = ""
    end_date_iso: str = ""
    batch_size: int = 50
    stages: dict[StageKey, StageStatus] = field(
        default_factory=lambda: {
            "discovery": "pending",
            "transfer": "pending",
            "create": "pending",
        },
    )
    items: dict[str, ItemState] = field(default_factory=dict)
    batches: dict[str, BatchState] = field(default_factory=dict)

    def touch(self) -> None:
        """Set ``updated_at`` to the current UTC ISO timestamp."""
        self.updated_at = _utc_now_iso()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full session for JSON or document databases.

        Returns:
            Nested plain dict suitable for :func:`json.dumps`.
        """
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "start_date_iso": self.start_date_iso,
            "end_date_iso": self.end_date_iso,
            "batch_size": self.batch_size,
            "stages": dict(self.stages),
            "items": {k: v.to_dict() for k, v in self.items.items()},
            "batches": {k: v.to_dict() for k, v in self.batches.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionState:
        """Deserialize session JSON produced by :meth:`to_dict`.

        Args:
            data: Top-level session mapping.

        Returns:
            Reconstructed :class:`SessionState`.
        """
        items_raw = data.get("items") or {}
        batches_raw = data.get("batches") or {}
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            session_id=str(data.get("session_id", "")),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            start_date_iso=str(data.get("start_date_iso", "")),
            end_date_iso=str(data.get("end_date_iso", "")),
            batch_size=int(data.get("batch_size", 50)),
            stages=dict(data.get("stages") or {}),  # type: ignore[arg-type]
            items={k: ItemState.from_dict(v) for k, v in items_raw.items()},
            batches={k: BatchState.from_dict(v) for k, v in batches_raw.items()},
        )


def new_session(
    session_id: str,
    *,
    start_date_iso: str,
    end_date_iso: str,
    batch_size: int,
) -> SessionState:
    """Create an empty session with timestamps and stage defaults initialized.

    Args:
        session_id: External key used for persistence lookups.
        start_date_iso: Capture window start as ISO string.
        end_date_iso: Capture window end as ISO string.
        batch_size: Transfer batch size recorded for later stages.

    Returns:
        New :class:`SessionState` with ``discovery``/``transfer``/``create`` set to ``pending``.
    """
    now = _utc_now_iso()
    return SessionState(
        session_id=session_id,
        created_at=now,
        updated_at=now,
        start_date_iso=start_date_iso,
        end_date_iso=end_date_iso,
        batch_size=batch_size,
    )


class SyncStateBackend(Protocol):
    """Storage backend for :class:`SessionState`."""

    def load(self, session_id: str) -> SessionState | None:
        """Load a session by id.

        Args:
            session_id: Same key passed to :func:`new_session` / orchestrator.

        Returns:
            Parsed state, or ``None`` if no document exists.
        """

    def save(self, state: SessionState) -> None:
        """Atomically persist ``state`` (semantics defined by the implementation).

        Args:
            state: Complete session document to store.

        Raises:
            OSError: Implementations may propagate IO failures from the storage layer.
        """


__all__ = [
    "BatchState",
    "ErrorRecord",
    "ItemCreateStatus",
    "ItemState",
    "MediaType",
    "SessionState",
    "StageKey",
    "StageStatus",
    "SyncStateBackend",
    "media_type_for_filename",
    "new_session",
]
