"""Pipeline stages for GoPro → Google Photos sync (discovery, transfer, create).

Stage classes are composed by :class:`~q2google.sync.GoProToPhotosSync`. The package also re-exports
``DEFAULT_DOWNLOAD_CHUNK_SIZE`` from configuration for backward compatibility.
"""

from q2google.config import DEFAULT_DOWNLOAD_CHUNK_SIZE
from q2google.stages.create import CreateStage
from q2google.stages.discovery import DiscoveryStage
from q2google.stages.transfer import TransferStage

__all__ = [
    "DEFAULT_DOWNLOAD_CHUNK_SIZE",
    "CreateStage",
    "DiscoveryStage",
    "TransferStage",
]
