"""Mutable counters for a single sync run (transfer-stage byte and timing totals).

Used by :class:`~q2google.stages.transfer.TransferStage` when a caller passes an instance into
:meth:`~q2google.sync.GoProToPhotosSync.sync_date_range`.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["SyncTransferMetrics"]


@dataclass
class SyncTransferMetrics:
    """Aggregates CDN download and Google upload volume and wall-clock phase times.

    Attributes:
        bytes_downloaded: Sum of local file sizes produced by successful CDN GETs in this run.
        bytes_uploaded: Sum of bytes successfully sent via resumable upload (file sizes uploaded).
        seconds_downloading: Wall time spent awaiting CDN download batches (per-batch sum).
        seconds_uploading: Wall time spent awaiting resumable upload batches (per-batch sum).
        seconds_transfer_wall: Wall time for the whole transfer stage body (excluding empty skip).
    """

    bytes_downloaded: int = 0
    bytes_uploaded: int = 0
    seconds_downloading: float = 0.0
    seconds_uploading: float = 0.0
    seconds_transfer_wall: float = 0.0
