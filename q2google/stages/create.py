"""Create stage: ``mediaItems:batchCreate`` using stored upload tokens."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from q2google.photos import GooglePhotosClient, MediaItemBatchCreateResponse
from q2google.stages.common import batched, error_record, restored_upload_session
from q2google.state.base import BatchState, SessionState

PersistFn = Callable[[SessionState], Awaitable[None]]


@dataclass
class CreateStage:
    """Register completed uploads with Google Photos in batches of ``library_batch_size``.

    Attributes:
        photos: Client used to build ``batchCreate`` requests.
        persist: Async callback after meaningful state mutations.
        library_batch_size: Maximum items per API batch (must not exceed API limit of 50).
    """

    photos: GooglePhotosClient
    persist: PersistFn
    library_batch_size: int

    @staticmethod
    def eligible_file_names(state: SessionState) -> list[str]:
        """List filenames ready for ``batchCreate`` (completed transfer, pending/failed create).

        Args:
            state: Session containing upload tokens.

        Returns:
            Sorted filenames eligible for this stage.
        """
        names: list[str] = []
        for file_name, item in state.items.items():
            if item.transfer_status != "completed" or not item.upload_token:
                continue
            if item.create_status in ("pending", "failed"):
                names.append(file_name)
        names.sort()
        return names

    async def run(
        self,
        state: SessionState,
        *,
        fail_fast: bool,
    ) -> list[MediaItemBatchCreateResponse]:
        """Execute ``batchCreate`` for all eligible items.

        Skips batches already marked completed in ``state.batches``.

        Args:
            state: Mutable session with upload tokens populated.
            fail_fast: When ``True``, abort after the first batch failure once state is saved.

        Returns:
            Combined successful responses from each completed batch in order.

        Raises:
            Exception: Re-raised from failed batches when ``fail_fast`` is ``True``, or on
                unexpected errors after marking the create stage failed.
        """
        eligible = self.eligible_file_names(state)
        if not eligible:
            state.stages["create"] = "completed"
            await self.persist(state)
            return []

        state.stages["create"] = "running"
        await self.persist(state)

        out: list[MediaItemBatchCreateResponse] = []
        try:
            for batch_index, name_batch in enumerate(batched(eligible, self.library_batch_size)):
                key = str(batch_index)
                existing = state.batches.get(key)
                if existing is not None and existing.status == "completed":
                    continue

                batch_state = BatchState(
                    batch_index=batch_index,
                    file_names=list(name_batch),
                    status="running",
                )
                state.batches[key] = batch_state
                await self.persist(state)

                sessions = [restored_upload_session(state.items[fn].upload_token or "") for fn in name_batch]
                try:
                    responses = await self.photos.create_media_items_from_upload_sessions(
                        name_batch,
                        sessions,
                    )
                except Exception as exc:
                    batch_state.status = "failed"
                    batch_state.error = error_record(exc, 1)
                    batch_state.responses_json = None
                    for fn in name_batch:
                        item = state.items[fn]
                        item.create_status = "failed"
                        item.errors["create"] = error_record(exc, 1)
                    await self.persist(state)
                    logging.exception("batchCreate failed for batch %s", batch_index)
                    if fail_fast:
                        raise
                    continue

                batch_state.status = "completed"
                batch_state.responses_json = [r.model_dump_json() for r in responses]
                batch_state.error = None
                for fn in name_batch:
                    state.items[fn].create_status = "completed"
                    state.items[fn].errors.pop("create", None)
                await self.persist(state)
                out.extend(responses)

            state.stages["create"] = "completed"
            await self.persist(state)
            return out
        except Exception:
            state.stages["create"] = "failed"
            await self.persist(state)
            raise
