"""Public package API for q2google.

Exports the main orchestrator (``GoProToPhotosSync``), Google Photos façade types, session
persistence protocols, and settings helpers.
"""

from q2google.config import Q2GoogleSettings, get_settings
from q2google.gphotos.auth import GooglePhotosOAuth
from q2google.photos import GooglePhotosClient
from q2google.state.base import SessionState, SyncStateBackend
from q2google.state.local import JsonFileBackend
from q2google.sync import GoProToPhotosSync

__all__ = [
    "GoProToPhotosSync",
    "GooglePhotosClient",
    "GooglePhotosOAuth",
    "JsonFileBackend",
    "Q2GoogleSettings",
    "SessionState",
    "SyncStateBackend",
    "get_settings",
]
