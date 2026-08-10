"""Transfer stage: CDN download plus Google resumable upload."""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import aiofiles
import aiohttp

from q2google.metrics import SyncTransferMetrics
from q2google.photos import GooglePhotosClient
from q2google.stages.common import CdnAsset, batched, error_record
from q2google.state.base import MediaType, SessionState

PersistFn = Callable[[SessionState], Awaitable[None]]


@dataclass
class TransferStage:
    """Download pending CDN assets and upload them via :class:`~q2google.photos.GooglePhotosClient`.

    Attributes:
        photos: Client performing resumable uploads.
        persist: Async callback after meaningful state mutations.
        download_chunk_size: Bytes per ``iter_chunked`` read/write when streaming downloads.
        cdn_sock_connect_seconds: Connect timeout for CDN sessions (``None`` uses library default).
        temp_dir_prefix: Prefix passed to :class:`tempfile.TemporaryDirectory`.
    """

    photos: GooglePhotosClient
    persist: PersistFn
    download_chunk_size: int
    cdn_sock_connect_seconds: float | None
    temp_dir_prefix: str

    async def download_url_to_file(
        self,
        client: aiohttp.ClientSession,
        url: str,
        dest: Path,
        *,
        chunk_size: int | None = None,
    ) -> int:
        """Stream ``url`` to ``dest`` using aiofiles and return total bytes written.

        Args:
            client: Caller-owned HTTP session for the GET.
            url: Absolute CDN URL.
            dest: Output path (parents created as needed).
            chunk_size: Override for read/write chunk size; defaults to ``download_chunk_size``.

        Returns:
            Number of bytes written.

        Raises:
            aiohttp.ClientResponseError: When the HTTP status indicates failure.
            OSError: When ``Content-Length`` does not match bytes written.
        """
        size = chunk_size if chunk_size is not None else self.download_chunk_size
        async with client.get(url) as response:
            response.raise_for_status()
            expected = response.content_length
            dest.parent.mkdir(parents=True, exist_ok=True)

            written = 0
            async with aiofiles.open(dest, "wb") as out_file:
                async for chunk in response.content.iter_chunked(size):
                    await out_file.write(chunk)
                    written += len(chunk)

            if expected is not None and written != expected:
                msg = f"Incomplete download: wrote {written} bytes, Content-Length was {expected} ({dest.name})"
                raise OSError(msg)
        return written

    async def _download_chunk(
        self,
        download_client: aiohttp.ClientSession,
        tmp_path: Path,
        batch: Sequence[tuple[str, CdnAsset]],
    ) -> list[tuple[str, Path]]:
        async def _download_one(file_name: str, asset: CdnAsset) -> tuple[str, Path]:
            dest = tmp_path / Path(file_name).name
            nbytes = await self.download_url_to_file(download_client, asset.url, dest)
            logging.info("Saved %s (%s bytes)", file_name, nbytes)
            return file_name, dest

        return await asyncio.gather(*[_download_one(fn, a) for fn, a in batch])

    @staticmethod
    def _delete_chunk_files(batch_paths: Sequence[tuple[str, Path]]) -> None:
        """Remove temporary files produced for one transfer batch."""
        for _file_name, path in batch_paths:
            path.unlink(missing_ok=True)

    @staticmethod
    def pending_file_names(
        state: SessionState,
        *,
        media_type: MediaType | None = None,
    ) -> list[str]:
        """Return sorted filenames needing download/upload based on discovery and transfer status.

        Args:
            state: Session containing partially completed items.
            media_type: When set, only include items whose :attr:`~q2google.state.base.ItemState.media_type`
                matches (``photo`` or ``video``).

        Returns:
            Filenames eligible for transfer retry (pending or failed transfer).
        """
        out: list[str] = []
        for file_name, item in state.items.items():
            if item.discovery_status != "completed" or not item.download_url:
                continue
            if media_type is not None and item.media_type != media_type:
                continue
            if item.transfer_status in ("pending", "failed"):
                out.append(file_name)
        out.sort()
        return out

    async def run(
        self,
        state: SessionState,
        *,
        batch_size: int | None = None,
        photo_batch_size: int | None = None,
        video_batch_size: int | None = None,
        fail_fast: bool,
        metrics: SyncTransferMetrics | None = None,
    ) -> None:
        """Process pending transfers, optionally with distinct photo/video batch sizes.

        Pending photos are transferred first (in filename order), then pending videos.
        Each media type uses its own batch size.

        Args:
            state: Mutable session updated with tokens and statuses.
            batch_size: When set, used for both photo and video batches (overrides per-type sizes).
            photo_batch_size: Files per concurrent cycle for photo items; required when
                ``batch_size`` is ``None``.
            video_batch_size: Files per concurrent cycle for video items; required when
                ``batch_size`` is ``None``.
            fail_fast: When ``True``, re-raise after persisting the first blocking error.
            metrics: Optional mutable aggregate for byte counts and phase timings.

        Raises:
            ValueError: When neither ``batch_size`` nor both per-type sizes are provided.
            BaseException: Propagates upload or download failures when ``fail_fast`` is ``True``.
        """
        if batch_size is not None:
            effective_photo_batch = batch_size
            effective_video_batch = batch_size
        elif photo_batch_size is not None and video_batch_size is not None:
            effective_photo_batch = photo_batch_size
            effective_video_batch = video_batch_size
        else:
            raise ValueError(
                "Provide batch_size, or both photo_batch_size and video_batch_size",
            )

        pending_photos = self.pending_file_names(state, media_type="photo")
        pending_videos = self.pending_file_names(state, media_type="video")
        if not pending_photos and not pending_videos:
            state.stages["transfer"] = "completed"
            await self.persist(state)
            return

        state.stages["transfer"] = "running"
        await self.persist(state)

        download_timeout = aiohttp.ClientTimeout(
            total=None,
            sock_connect=self.cdn_sock_connect_seconds,
        )
        t_wall_start = time.perf_counter()
        try:
            with tempfile.TemporaryDirectory(prefix=self.temp_dir_prefix) as tmp:
                tmp_path = Path(tmp)
                async with aiohttp.ClientSession(timeout=download_timeout) as download_client:
                    for media_type, pending, type_batch_size in (
                        ("photo", pending_photos, effective_photo_batch),
                        ("video", pending_videos, effective_video_batch),
                    ):
                        if not pending:
                            continue
                        for batch_index, name_batch in enumerate(
                            batched(pending, type_batch_size),
                            start=1,
                        ):
                            logging.info(
                                "Transfer %s batch %s: %s file(s)",
                                media_type,
                                batch_index,
                                len(name_batch),
                            )
                            batch_assets: list[tuple[str, CdnAsset]] = []
                            for fn in name_batch:
                                it = state.items[fn]
                                assert it.download_url is not None
                                batch_assets.append((fn, SimpleNamespace(url=it.download_url)))
                            try:
                                t_dl = time.perf_counter()
                                paths = await self._download_chunk(
                                    download_client,
                                    tmp_path,
                                    batch_assets,
                                )
                                if metrics is not None:
                                    metrics.seconds_downloading += time.perf_counter() - t_dl
                                    for _, p in paths:
                                        metrics.bytes_downloaded += p.stat().st_size
                            except Exception as exc:
                                for fn in name_batch:
                                    item = state.items[fn]
                                    item.transfer_status = "failed"
                                    item.errors["transfer"] = error_record(exc, 1)
                                    item.create_status = "skipped"
                                await self.persist(state)
                                if fail_fast:
                                    raise exc
                                continue

                            path_sizes = {p: p.stat().st_size for _, p in paths}
                            t_ul = time.perf_counter()
                            results = await asyncio.gather(
                                *[self.photos.upload_file_path(fn, path) for fn, path in paths],
                                return_exceptions=True,
                            )
                            if metrics is not None:
                                metrics.seconds_uploading += time.perf_counter() - t_ul

                            self._delete_chunk_files(paths)

                            for (fn, path), res in zip(paths, results, strict=True):
                                item = state.items[fn]
                                if isinstance(res, BaseException):
                                    item.transfer_status = "failed"
                                    item.errors["transfer"] = error_record(res, 1)
                                    item.upload_token = None
                                    item.create_status = "skipped"
                                    logging.exception("Upload failed for %s", fn)
                                    if fail_fast:
                                        await self.persist(state)
                                        raise res
                                else:
                                    item.transfer_status = "completed"
                                    item.upload_token = res.upload_token
                                    item.create_status = "pending"
                                    item.errors.pop("transfer", None)
                                    if metrics is not None:
                                        metrics.bytes_uploaded += path_sizes[path]
                            await self.persist(state)

            state.stages["transfer"] = "completed"
            await self.persist(state)
        except Exception:
            state.stages["transfer"] = "failed"
            await self.persist(state)
            raise
        finally:
            if metrics is not None:
                metrics.seconds_transfer_wall = time.perf_counter() - t_wall_start
