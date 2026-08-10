"""Discovery stage: GoPro listing and CDN URL resolution."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from gopro_api import AsyncGoProClient

from q2google.state.base import ItemState, SessionState, media_type_for_filename

PersistFn = Callable[[SessionState], Awaitable[None]]


@dataclass
class DiscoveryStage:
    """List cloud media for the session window and fill ``download_url`` on each item.

    Attributes:
        gopro: Async GoPro client for listing and URL resolution.
        persist: Async callback invoked after mutating ``SessionState`` (typically saves to backend).
    """

    gopro: AsyncGoProClient
    persist: PersistFn

    async def run(self, state: SessionState) -> None:
        """Execute or skip discovery for ``state``.

        Idempotent when ``state.stages[\"discovery\"]`` is already ``completed``.

        Args:
            state: Session whose ``start_date_iso`` / ``end_date_iso`` define the query window.

        Raises:
            Exception: Any error from GoPro APIs; sets discovery stage to ``failed`` and re-raises.
        """
        if state.stages.get("discovery") == "completed":
            logging.info("Discovery stage already completed; skipping")
            return

        state.stages["discovery"] = "running"
        await self.persist(state)
        try:
            logging.info("Listing media items (discovery)")
            media_items = await self.gopro.list_media_items(
                datetime.fromisoformat(state.start_date_iso),
                datetime.fromisoformat(state.end_date_iso),
            )
            logging.info("Resolving download URLs (discovery)")
            media_files = await self.gopro.get_download_url(media_items)
            for file_name, asset in media_files.items():
                item = state.items.setdefault(
                    file_name,
                    ItemState(
                        file_name=file_name,
                        media_type=media_type_for_filename(file_name),
                    ),
                )
                item.media_type = media_type_for_filename(file_name)
                item.download_url = asset.url
                item.discovery_status = "completed"
            state.stages["discovery"] = "completed"
            await self.persist(state)
        except Exception:
            state.stages["discovery"] = "failed"
            logging.exception("Discovery stage failed")
            await self.persist(state)
            raise
