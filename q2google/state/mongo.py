"""MongoDB-backed :class:`~q2google.state.base.SyncStateBackend`.

Stores session state across three collections that mirror the filesystem layout used by
:class:`~q2google.state.local.JsonFileBackend`:

- **sessions** — one document per session containing metadata and stage statuses.
- **items** — one document per ``(session_id, file_name)`` pair.
- **batches** — one document per ``(session_id, batch_index)`` pair.

The database name is parsed from the URI path component
(``mongodb://host:27017/q2google`` → database ``q2google``).
When the path is absent or ``/``, the name defaults to ``q2google``.

Requires the ``pymongo`` package (``pip install q2google[mongo]``).

Layout::

    <database>/
      sessions   { session_id, schema_version, created_at, updated_at,
                   start_date_iso, end_date_iso, batch_size, stages }
      items      { session_id, file_name, media_id, download_url,
                   discovery_status, transfer_status, create_status,
                   upload_token, errors }
      batches    { session_id, batch_index, file_names, status,
                   responses_json, error }
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    import pymongo
    import pymongo.collection
    import pymongo.database

from q2google.state.base import SessionState

_DEFAULT_DB = "q2google"

_METADATA_KEYS: tuple[str, ...] = (
    "schema_version",
    "session_id",
    "created_at",
    "updated_at",
    "start_date_iso",
    "end_date_iso",
    "batch_size",
    "stages",
)


def _db_name_from_uri(uri: str) -> str:
    """Extract the database name from a MongoDB URI path component.

    Args:
        uri: Full MongoDB connection string, e.g. ``mongodb://host:27017/q2google``.

    Returns:
        Database name taken from the URI path, or ``"q2google"`` when absent.
    """
    path = urlparse(uri).path.lstrip("/")
    return path or _DEFAULT_DB


class MongoBackend:
    """Store each session across three MongoDB collections.

    Each :class:`~q2google.state.base.ItemState` and
    :class:`~q2google.state.base.BatchState` is upserted to its own document,
    matching the per-file isolation of :class:`~q2google.state.local.JsonFileBackend`.
    Session-level metadata lives in the ``sessions`` collection.

    Indexes are created lazily the first time :meth:`save` is called on a new instance,
    ensuring that the collections are usable without a separate setup step.
    """

    def __init__(self, uri: str) -> None:
        """Create the backend and connect to MongoDB.

        Args:
            uri: MongoDB connection string. The database name is parsed from the URI
                path component; defaults to ``"q2google"`` when absent.

        Raises:
            ImportError: When ``pymongo`` is not installed. Install it with
                ``pip install q2google[mongo]``.
        """
        try:
            import pymongo
        except ImportError as exc:
            raise ImportError("MongoBackend requires pymongo. Install it with: pip install q2google[mongo]") from exc

        self._client: pymongo.MongoClient[dict[str, Any]] = pymongo.MongoClient(uri)
        self._db: pymongo.database.Database[dict[str, Any]] = self._client[_db_name_from_uri(uri)]
        self._sessions: pymongo.collection.Collection[dict[str, Any]] = self._db["sessions"]
        self._items: pymongo.collection.Collection[dict[str, Any]] = self._db["items"]
        self._batches: pymongo.collection.Collection[dict[str, Any]] = self._db["batches"]
        self._indexes_ensured = False

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def _ensure_indexes(self) -> None:
        """Create unique compound indexes on first use.

        Idempotent — safe to call multiple times; MongoDB skips creation when the
        index already exists with the same specification.
        """
        if self._indexes_ensured:
            return
        import pymongo

        self._sessions.create_index([("session_id", pymongo.ASCENDING)], unique=True)
        self._items.create_index(
            [("session_id", pymongo.ASCENDING), ("file_name", pymongo.ASCENDING)],
            unique=True,
        )
        self._batches.create_index(
            [("session_id", pymongo.ASCENDING), ("batch_index", pymongo.ASCENDING)],
            unique=True,
        )
        self._indexes_ensured = True

    # ------------------------------------------------------------------
    # SyncStateBackend interface
    # ------------------------------------------------------------------

    def load(self, session_id: str) -> SessionState | None:
        """Load ``SessionState`` for ``session_id`` from MongoDB.

        Fetches the session metadata document from ``sessions``, then all item
        documents from ``items`` and all batch documents from ``batches`` for the
        same ``session_id``.

        Args:
            session_id: Session key used when saving.

        Returns:
            Reconstructed :class:`~q2google.state.base.SessionState`, or ``None`` if
            no session document exists for ``session_id``.
        """
        meta = self._sessions.find_one({"session_id": session_id}, {"_id": 0})
        if meta is None:
            return None

        data: dict[str, Any] = dict(meta)

        data["items"] = {doc["file_name"]: doc for doc in self._items.find({"session_id": session_id}, {"_id": 0})}
        data["batches"] = {
            str(doc["batch_index"]): doc for doc in self._batches.find({"session_id": session_id}, {"_id": 0})
        }

        return SessionState.from_dict(data)

    def save(self, state: SessionState) -> None:
        """Persist ``state`` by upserting documents into all three collections.

        Each item and batch is upserted independently, so concurrent writers
        updating different items never conflict.

        Args:
            state: Complete session document to store.
        """
        self._ensure_indexes()

        full = state.to_dict()
        sid = state.session_id

        meta = {k: full[k] for k in _METADATA_KEYS}
        self._sessions.replace_one({"session_id": sid}, meta, upsert=True)

        for item_doc in full["items"].values():
            self._items.replace_one(
                {"session_id": sid, "file_name": item_doc["file_name"]},
                {"session_id": sid, **item_doc},
                upsert=True,
            )

        for batch_doc in full["batches"].values():
            self._batches.replace_one(
                {"session_id": sid, "batch_index": batch_doc["batch_index"]},
                {"session_id": sid, **batch_doc},
                upsert=True,
            )


__all__ = ["MongoBackend"]
