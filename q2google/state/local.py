"""Filesystem-backed :class:`~q2google.state.base.SyncStateBackend`.

Writes UTF-8 JSON per session using a temp file and :func:`os.replace` for atomic publish.
Intended for single-writer use; concurrent writers to the same session path are unsupported.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from q2google.state.base import SessionState


class JsonFileBackend:
    """Store each session as ``{root}/{sanitized_session_id}.json``."""

    def __init__(self, root: str | Path) -> None:
        """Create the backend and ensure ``root`` exists.

        Args:
            root: Directory that will contain ``*.json`` session files.
        """
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        """Resolve a safe filename under ``root`` for ``session_id``.

        Args:
            session_id: External session key (path separators and ``..`` neutralized).

        Returns:
            Absolute path to the JSON file for this session.
        """
        safe = session_id.replace(os.sep, "_").replace("..", "_")
        return self._root / f"{safe}.json"

    def load(self, session_id: str) -> SessionState | None:
        """Load ``SessionState`` from disk when the JSON file exists.

        Args:
            session_id: Session key used when saving.

        Returns:
            Parsed state, or ``None`` if the file is missing.

        Raises:
            json.JSONDecodeError: If the file contents are not valid JSON.
        """
        path = self._path(session_id)
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        return SessionState.from_dict(data)

    def save(self, state: SessionState) -> None:
        """Write ``state`` atomically via temp file + replace.

        Args:
            state: Document whose ``session_id`` determines the output filename.

        Raises:
            OSError: On failure to write the temp file or replace the destination.
        """
        path = self._path(state.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state.to_dict(), indent=2, ensure_ascii=False)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        try:
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            if tmp.is_file():
                tmp.unlink(missing_ok=True)
            raise


__all__ = ["JsonFileBackend"]
