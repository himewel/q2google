"""Filesystem-backed :class:`~q2google.state.base.SyncStateBackend`.

Stores each session as a directory tree with one JSON file per item and one per batch,
making concurrent writes to different items safe by construction.  Each individual file
is published atomically via a temp file and :func:`os.replace`.

Layout::

    {root}/
      {session_id}/
        meta.json               # session metadata + stages (no items, no batches)
        items/
          {safe_file_name}.json # one file per ItemState
        batches/
          {batch_key}.json      # one file per BatchState

Legacy flat-file sessions (``{session_id}.json``) written by older versions of this
module are still readable; ``load`` detects and falls back to that format transparently.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from q2google.state.base import SessionState

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


def _safe_name(name: str) -> str:
    """Sanitize ``name`` for safe use as a filesystem path component.

    Args:
        name: Raw string such as a session id, GoPro filename, or batch key.

    Returns:
        Version of ``name`` with path separators and ``..`` replaced by ``_``.
    """
    return name.replace(os.sep, "_").replace("..", "_")


class JsonFileBackend:
    """Store each session under ``{root}/{session_id}/`` as a directory of JSON files.

    Each :class:`~q2google.state.base.ItemState` and
    :class:`~q2google.state.base.BatchState` is written to its own file so that
    concurrent writers updating different items never conflict.  Session-level metadata
    (stages, timestamps) lives in ``meta.json`` and is still subject to last-write-wins
    semantics, but stage transitions are sequential in the current orchestrator so this
    is not a practical concern.
    """

    def __init__(self, root: str | Path) -> None:
        """Create the backend and ensure ``root`` exists.

        Args:
            root: Directory that will contain per-session subdirectories.
        """
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _session_dir(self, session_id: str) -> Path:
        """Return the session directory path for ``session_id``.

        Args:
            session_id: External session key.

        Returns:
            ``{root}/{safe(session_id)}/``
        """
        return self._root / _safe_name(session_id)

    def _meta_path(self, session_id: str) -> Path:
        """Return the path to the session metadata file.

        Args:
            session_id: External session key.

        Returns:
            ``{session_dir}/meta.json``
        """
        return self._session_dir(session_id) / "meta.json"

    def _item_path(self, session_id: str, file_name: str) -> Path:
        """Return the path to a single item file.

        Args:
            session_id: External session key.
            file_name: GoPro logical filename used as the item key.

        Returns:
            ``{session_dir}/items/{safe(file_name)}.json``
        """
        return self._session_dir(session_id) / "items" / f"{_safe_name(file_name)}.json"

    def _batch_path(self, session_id: str, batch_key: str) -> Path:
        """Return the path to a single batch file.

        Args:
            session_id: External session key.
            batch_key: String batch index used as the batch key.

        Returns:
            ``{session_dir}/batches/{safe(batch_key)}.json``
        """
        return self._session_dir(session_id) / "batches" / f"{_safe_name(batch_key)}.json"

    # ------------------------------------------------------------------
    # I/O primitive
    # ------------------------------------------------------------------

    def _atomic_write(self, path: Path, data: dict[str, Any]) -> None:
        """Write ``data`` to ``path`` atomically via a temporary file and :func:`os.replace`.

        Args:
            path: Destination file path; parent directory is created if absent.
            data: JSON-serializable mapping to persist.

        Raises:
            OSError: On failure to write the temp file or replace the destination.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, indent=2, ensure_ascii=False)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        try:
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            tmp.unlink(missing_ok=True)
            raise

    # ------------------------------------------------------------------
    # SyncStateBackend interface
    # ------------------------------------------------------------------

    def load(self, session_id: str) -> SessionState | None:
        """Load ``SessionState`` for ``session_id`` from disk.

        Falls back to the legacy flat-file format (``{session_id}.json``) when the
        session directory does not exist, so sessions written by older versions of this
        module remain readable without any migration step.

        Args:
            session_id: Session key used when saving.

        Returns:
            Parsed state, or ``None`` if neither the directory nor the legacy file exists.

        Raises:
            json.JSONDecodeError: If any JSON file on disk is malformed.
        """
        legacy = self._root / f"{_safe_name(session_id)}.json"
        if legacy.is_file():
            return SessionState.from_dict(json.loads(legacy.read_text(encoding="utf-8")))

        meta_path = self._meta_path(session_id)
        if not meta_path.is_file():
            return None

        session_dir = self._session_dir(session_id)
        data: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))

        data["items"] = {
            d["file_name"]: d
            for p in (session_dir / "items").glob("*.json")
            for d in (json.loads(p.read_text(encoding="utf-8")),)
        }
        data["batches"] = {
            str(d["batch_index"]): d
            for p in (session_dir / "batches").glob("*.json")
            for d in (json.loads(p.read_text(encoding="utf-8")),)
        }
        return SessionState.from_dict(data)

    def save(self, state: SessionState) -> None:
        """Persist ``state`` by writing metadata, items, and batches to separate files.

        Each file is written atomically.  Writers updating different items never
        conflict because they target distinct paths.

        Args:
            state: Complete session document to store.

        Raises:
            OSError: On failure to write any individual file.
        """
        full = state.to_dict()
        meta = {k: full[k] for k in _METADATA_KEYS}
        self._atomic_write(self._meta_path(state.session_id), meta)

        for file_name, item in full["items"].items():
            self._atomic_write(self._item_path(state.session_id, file_name), item)

        for batch_key, batch in full["batches"].items():
            self._atomic_write(self._batch_path(state.session_id, str(batch_key)), batch)


__all__ = ["JsonFileBackend"]
