"""Orchestration layer for GoPro cloud → Google Photos staged sync.

:class:`GoProToPhotosSync` loads or creates :class:`~q2google.state.base.SessionState`, then runs
:class:`~q2google.stages.discovery.DiscoveryStage`,
:class:`~q2google.stages.transfer.TransferStage`, and :class:`~q2google.stages.create.CreateStage`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TypeAlias

from gopro_api import AsyncGoProClient

from q2google.config import (
    DEFAULT_DOWNLOAD_CHUNK_SIZE,
    Q2GoogleSettings,
    get_settings,
)
from q2google.metrics import SyncTransferMetrics
from q2google.photos import (
    GooglePhotosClient,
    MediaItemBatchCreateResponse,
)
from q2google.stages import CreateStage, DiscoveryStage, TransferStage
from q2google.state.base import SessionState, StageKey, SyncStateBackend, new_session

StageCompleteCallback: TypeAlias = Callable[
    [StageKey, SessionState, list[MediaItemBatchCreateResponse] | None],
    Awaitable[None],
]
StageStartCallback: TypeAlias = Callable[[StageKey], Awaitable[None]]

__all__ = [
    "DEFAULT_DOWNLOAD_CHUNK_SIZE",
    "GoProToPhotosSync",
    "StageCompleteCallback",
    "StageStartCallback",
    "SyncTransferMetrics",
]


@dataclass
class GoProToPhotosSync:
    """Coordinate staged sync from GoPro cloud into Google Photos.

    Attributes:
        gopro: Async GoPro cloud client used during discovery.
        photos: Facade for resumable upload and ``mediaItems:batchCreate``.
        state_backend: Pluggable load/save for :class:`~q2google.state.base.SessionState`.
        settings: Defaults for batch sizes, chunking, and ``fail_fast`` behavior.
    """

    gopro: AsyncGoProClient
    photos: GooglePhotosClient
    state_backend: SyncStateBackend
    settings: Q2GoogleSettings = field(default_factory=get_settings)
    _discovery: DiscoveryStage = field(init=False, repr=False)
    _transfer: TransferStage = field(init=False, repr=False)
    _create: CreateStage = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Construct stage objects bound to this orchestrator's clients and settings."""
        self._discovery = DiscoveryStage(self.gopro, self._persist_state)
        self._transfer = TransferStage(
            self.photos,
            self._persist_state,
            download_chunk_size=self.settings.download_chunk_size_bytes,
            cdn_sock_connect_seconds=self.settings.cdn_download_sock_connect_seconds,
            temp_dir_prefix=self.settings.temp_dir_prefix,
        )
        self._create = CreateStage(
            self.photos,
            self._persist_state,
            library_batch_size=self.settings.photos_library_batch_size,
        )

    async def _persist_state(self, state: SessionState) -> None:
        """Update ``updated_at`` and persist ``state`` via ``state_backend`` (thread offload).

        Args:
            state: Mutable session document to save.
        """
        state.touch()
        await asyncio.to_thread(self.state_backend.save, state)

    async def sync_date_range(
        self,
        start_date: datetime,
        end_date: datetime,
        *,
        session_id: str,
        batch_size: int | None = None,
        fail_fast: bool | None = None,
        on_stage_start: StageStartCallback | None = None,
        on_stage_complete: StageCompleteCallback | None = None,
        transfer_metrics: SyncTransferMetrics | None = None,
    ) -> list[MediaItemBatchCreateResponse]:
        """Run discovery → transfer → create for ``session_id``.

        Uses ``state_backend`` for checkpoints. When persisted state already exists, caller-supplied
        ``start_date``, ``end_date``, and ``batch_size`` are ignored in favor of the stored session.

        Args:
            start_date: Capture window start (new sessions only).
            end_date: Capture window end (new sessions only).
            session_id: Stable document key for load/resume.
            batch_size: When set, overrides both photo and video transfer batch sizes for this run
                (and is stored on new sessions). When ``None``, uses
                ``settings.batch_size_for(\"photo\"|\"video\")``.
            fail_fast: When not ``None``, overrides ``settings.fail_fast``.
            on_stage_start: Optional async hook invoked immediately before each stage begins.
            on_stage_complete: Optional async hook invoked after each stage finishes (including on
                failure). For ``create``, the third argument is the list returned so far from that
                stage; it is empty when the stage raised before returning.
            transfer_metrics: Optional mutable counters filled during the transfer stage (CDN bytes,
                uploaded bytes, phase and wall times).

        Returns:
            Flattened list of batch-create responses from this invocation, in batch order.
        """
        if batch_size is None:
            photo_batch = self.settings.batch_size_for("photo")
            video_batch = self.settings.batch_size_for("video")
            session_batch = photo_batch
        else:
            photo_batch = batch_size
            video_batch = batch_size
            session_batch = batch_size
        effective_fail_fast = self.settings.fail_fast if fail_fast is None else fail_fast

        loaded = await asyncio.to_thread(self.state_backend.load, session_id)
        if loaded is None:
            state = new_session(
                session_id,
                start_date_iso=start_date.isoformat(),
                end_date_iso=end_date.isoformat(),
                batch_size=session_batch,
            )
            await self._persist_state(state)
        else:
            state = loaded

        all_responses: list[MediaItemBatchCreateResponse] = []

        try:
            if on_stage_start is not None:
                await on_stage_start("discovery")
            await self._discovery.run(state)
        finally:
            if on_stage_complete is not None:
                await on_stage_complete("discovery", state, None)

        try:
            if on_stage_start is not None:
                await on_stage_start("transfer")
            await self._transfer.run(
                state,
                photo_batch_size=photo_batch,
                video_batch_size=video_batch,
                fail_fast=effective_fail_fast,
                metrics=transfer_metrics,
            )
        finally:
            if on_stage_complete is not None:
                await on_stage_complete("transfer", state, None)

        batch_responses: list[MediaItemBatchCreateResponse] = []
        try:
            if on_stage_start is not None:
                await on_stage_start("create")
            batch_responses = await self._create.run(state, fail_fast=effective_fail_fast)
        finally:
            if on_stage_complete is not None:
                await on_stage_complete("create", state, batch_responses)

        all_responses.extend(batch_responses)

        logging.debug(
            "Session %s — media item responses this run: %s",
            session_id,
            [response.model_dump_json() for response in all_responses],
        )
        return all_responses
