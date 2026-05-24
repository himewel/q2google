"""Session persistence models and built-in storage backends.

Re-exports types from :mod:`q2google.state.base`, :mod:`q2google.state.local`, and
:mod:`q2google.state.mongo` for convenient ``from q2google.state import …`` imports.

Use :func:`build_backend` to obtain the correct backend from a
:class:`~q2google.config.Q2GoogleSettings` instance without touching backend-specific
imports directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from q2google.state.base import (
    BatchState,
    ErrorRecord,
    ItemCreateStatus,
    ItemState,
    SessionState,
    StageKey,
    StageStatus,
    SyncStateBackend,
    new_session,
)
from q2google.state.local import JsonFileBackend

if TYPE_CHECKING:
    from q2google.config import Q2GoogleSettings
    from q2google.state.mongo import MongoBackend


def build_backend(cfg: Q2GoogleSettings) -> SyncStateBackend:
    """Return the appropriate :class:`SyncStateBackend` for the given settings.

    The ``state_uri`` field on *cfg* determines which backend is constructed:

    - ``mongodb://…`` → :class:`~q2google.state.mongo.MongoBackend` (requires
      ``pymongo``; install with ``pip install q2google[mongo]``).
    - ``None`` → :class:`~q2google.state.local.JsonFileBackend` using
      ``cfg.state_dir`` (default, no extra dependencies).

    Adding a new backend in the future only requires a new ``elif`` branch here
    and a new backend module — no changes to :class:`~q2google.config.Q2GoogleSettings`
    are needed.

    Args:
        cfg: Application settings loaded from the environment or ``.env``.

    Returns:
        A ready-to-use :class:`SyncStateBackend` instance.

    Raises:
        ImportError: When a ``mongodb://`` URI is given but ``pymongo`` is not installed.
        ValueError: When ``state_uri`` contains an unrecognised scheme.
    """
    if cfg.state_uri is None:
        return JsonFileBackend(cfg.state_dir)

    from urllib.parse import urlparse

    scheme = urlparse(cfg.state_uri).scheme.lower()

    if scheme in ("mongodb", "mongodb+srv"):
        try:
            from q2google.state.mongo import MongoBackend
        except ImportError as exc:
            raise ImportError("MongoBackend requires pymongo. Install it with: pip install q2google[mongo]") from exc
        return MongoBackend(cfg.state_uri)

    raise ValueError(
        f"Unsupported state_uri scheme {scheme!r}. "
        "Supported schemes: mongodb://, mongodb+srv://. "
        "Leave Q2GOOGLE_STATE_URI unset to use the filesystem backend."
    )


__all__ = [
    "BatchState",
    "ErrorRecord",
    "ItemCreateStatus",
    "ItemState",
    "JsonFileBackend",
    "MongoBackend",
    "SessionState",
    "StageKey",
    "StageStatus",
    "SyncStateBackend",
    "build_backend",
    "new_session",
]
