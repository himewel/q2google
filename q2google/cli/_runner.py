"""Async runner for the GoPro → Google Photos sync pipeline."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from gopro_api import AsyncGoProClient

from q2google.cli._printer import SyncPrinter
from q2google.config import Q2GoogleSettings
from q2google.gphotos.api import GooglePhotosAPI
from q2google.gphotos.auth import GooglePhotosOAuth
from q2google.gphotos.models import PhotosScopes
from q2google.metrics import SyncTransferMetrics
from q2google.photos import GooglePhotosClient, MediaItemBatchCreateResponse
from q2google.state.base import SessionState, StageKey, SyncStateBackend
from q2google.sync import GoProToPhotosSync

_STAGE_STEP: dict[str, int] = {"discovery": 1, "transfer": 2, "create": 3}
_TOTAL_STAGES = 3


async def _run_sync(
    *,
    cfg: Q2GoogleSettings,
    start: datetime,
    end: datetime,
    credentials: Path,
    token: Path,
    state_backend: SyncStateBackend,
    session_id: str,
    chunk_multiplier: int,
    max_items: int,
    prefer_height: int,
    batch_size: int | None,
    fail_fast: bool | None,
    printer: SyncPrinter,
) -> tuple[list[MediaItemBatchCreateResponse], SyncTransferMetrics]:
    """Open GoPro and Google Photos clients and run a full staged sync for one session.

    Args:
        cfg: Resolved settings (timeouts, defaults merged from env and CLI).
        start: Capture window start for new sessions (ignored when resuming existing state).
        end: Capture window end for new sessions (ignored when resuming existing state).
        credentials: OAuth client secrets JSON path.
        token: Path to store the user OAuth token.
        state_backend: Pre-built :class:`~q2google.state.base.SyncStateBackend` instance
            created by :func:`~q2google.state.build_backend`. Passed in rather than
            constructed here so that callers can inspect it before and after the run.
        session_id: Stable session key used for load/resume.
        chunk_multiplier: Resumable upload chunk multiplier for
            :class:`~q2google.photos.GooglePhotosClient`.
        max_items: Maximum media items listed from GoPro cloud.
        prefer_height: Preferred download height for GoPro assets.
        batch_size: Transfer batch size for new sessions; ``None`` uses ``cfg.sync_batch_size``.
        fail_fast: Whether to abort on first error; ``None`` uses ``cfg.fail_fast``.
        printer: Rich console renderer used to report stage completions.

    Returns:
        Batch-create responses from this invocation and transfer-stage byte/time metrics.
    """
    creds = GooglePhotosOAuth(
        str(credentials),
        scopes=[
            PhotosScopes.LIBRARY_APPENDONLY,
            PhotosScopes.LIBRARY_READONLY_APP_CREATED,
            PhotosScopes.LIBRARY_EDIT_APP_CREATED,
        ],
        token_file=str(token),
    )

    logging.debug("session_id=%s backend=%r", session_id, type(state_backend).__name__)

    async with (
        AsyncGoProClient(
            access_token=cfg.gopro_access_token,
            max_items=max_items,
            prefer_height=prefer_height,
        ) as gopro,
        GooglePhotosAPI(
            credentials=creds,
            timeout=cfg.google_photos_timeout_seconds,
        ) as google_photos_api,
    ):
        photos = GooglePhotosClient(google_photos_api, chunk_granularity_multiplier=chunk_multiplier)
        syncer = GoProToPhotosSync(gopro, photos, state_backend=state_backend, settings=cfg)

        transfer_metrics = SyncTransferMetrics()

        async def _report_stage_start(st: StageKey) -> None:
            printer.start_stage(st, step=_STAGE_STEP[st], total=_TOTAL_STAGES)

        async def _report_stage(
            st: StageKey,
            st_state: SessionState,
            responses: list[MediaItemBatchCreateResponse] | None,
        ) -> None:
            printer.print_stage_summary(
                st,
                st_state,
                responses,
                transfer_metrics=transfer_metrics if st == "transfer" else None,
            )

        responses = await syncer.sync_date_range(
            start_date=start,
            end_date=end,
            session_id=session_id,
            batch_size=batch_size,
            fail_fast=fail_fast,
            on_stage_start=_report_stage_start,
            on_stage_complete=_report_stage,
            transfer_metrics=transfer_metrics,
        )
        return responses, transfer_metrics
