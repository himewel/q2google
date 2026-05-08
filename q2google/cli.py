"""Command-line interface built with Typer.

Options combine with :func:`q2google.config.get_settings`: explicit flags override environment
and ``.env`` defaults.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import typer
from gopro_api import AsyncGoProClient

from q2google.config import Q2GoogleSettings, get_settings
from q2google.metrics import SyncTransferMetrics
from q2google.gphotos.api import GooglePhotosAPI
from q2google.gphotos.auth import GooglePhotosOAuth
from q2google.gphotos.models import PhotosScopes
from q2google.photos import GooglePhotosClient, MediaItemBatchCreateResponse
from q2google.state.base import ItemState, SessionState, StageKey
from q2google.state.local import JsonFileBackend
from q2google.sync import GoProToPhotosSync

app = typer.Typer(help="q2google — sync GoPro cloud media to Google Photos.")

_NOISY_LOGGER_NAMES = (
    "aiohttp",
    "aiohttp.client",
    "google",
    "google_auth_oauthlib",
    "urllib3",
    "gopro_api",
)


def _configure_cli_logging(*, explicit_level: str | None, verbose: bool) -> None:
    """Configure root logging for Typer; quiet by default, optional verbose or explicit level.

    Third-party libraries stay at WARNING unless root level is DEBUG.

    Args:
        explicit_level: ``--log-level`` value when provided.
        verbose: ``True`` when ``-v`` / ``--verbose`` is set.
    """
    if explicit_level is not None:
        root_level = getattr(logging, explicit_level.upper(), logging.WARNING)
    elif verbose:
        root_level = logging.INFO
    else:
        root_level = logging.WARNING

    logging.basicConfig(
        level=root_level,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if root_level < logging.DEBUG:
        for name in _NOISY_LOGGER_NAMES:
            logging.getLogger(name).setLevel(logging.WARNING)

    if explicit_level is None:
        logging.getLogger("q2google").setLevel(logging.INFO if verbose else logging.WARNING)


def _format_duration_compact(seconds: float) -> str:
    """Format a duration in seconds without an ``Execution time:`` prefix."""
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes, sec = divmod(seconds, 60.0)
    if minutes < 60:
        return f"{int(minutes)}m {sec:.2f}s"
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours}h {minutes}m {sec:.2f}s"


def _format_execution_time(seconds: float) -> str:
    """Format wall-clock duration for the CLI summary (compact for short runs)."""
    return f"Execution time: {_format_duration_compact(seconds)}"


def _format_bytes_human(n: int) -> str:
    """Binary IEC-ish labels (KiB, MiB, GiB) for byte counts."""
    if n < 1024:
        return f"{n} B"
    kib = n / 1024
    if kib < 1024:
        return f"{kib:.2f} KiB"
    mib = n / (1024**2)
    if mib < 1024:
        return f"{mib:.2f} MiB"
    gib = n / (1024**3)
    return f"{gib:.2f} GiB"


def _format_rate_mib_s(bytes_count: int, seconds: float) -> str:
    """Average throughput in MiB/s; ``n/a`` when undefined."""
    if seconds <= 0 or bytes_count <= 0:
        return "n/a"
    mib_per_s = bytes_count / (1024 * 1024) / seconds
    return f"{mib_per_s:.2f} MiB/s"


def _transfer_throughput_lines(m: SyncTransferMetrics) -> list[str]:
    """Lines describing transfer-stage volume and average phase speeds."""
    if m.bytes_downloaded == 0 and m.bytes_uploaded == 0 and m.seconds_transfer_wall <= 0:
        return ["  (No transfer activity — stage skipped or idle.)"]
    return [
        f"  CDN downloaded: {_format_bytes_human(m.bytes_downloaded)}  "
        f"(avg {_format_rate_mib_s(m.bytes_downloaded, m.seconds_downloading)})",
        f"  Uploaded to Google: {_format_bytes_human(m.bytes_uploaded)}  "
        f"(avg {_format_rate_mib_s(m.bytes_uploaded, m.seconds_uploading)})",
        f"  Transfer stage wall time: {_format_duration_compact(m.seconds_transfer_wall)}",
    ]


def _format_stage_operations_summary(
    stage: StageKey,
    state: SessionState,
    batch_create_responses: list[MediaItemBatchCreateResponse] | None,
    *,
    transfer_metrics: SyncTransferMetrics | None = None,
) -> str:
    """Summarize per-item outcomes relevant right after one pipeline stage."""
    labels = {"discovery": "Discovery", "transfer": "Transfer", "create": "Create"}
    title = labels[stage]
    stage_status = state.stages.get(stage, "?")
    lines: list[str] = [f"--- {title} ({stage_status}) ---"]

    items = list(state.items.values())
    if stage == "discovery":
        lines.append(f"  Items in session: {len(items)}")
        lines.append(f"  URLs resolved: {sum(1 for i in items if i.discovery_status == 'completed')}")
        lines.append(f"  Discovery failed: {sum(1 for i in items if i.discovery_status == 'failed')}")
        pend = sum(1 for i in items if i.discovery_status in ("pending", "running"))
        if pend:
            lines.append(f"  Discovery pending / in progress: {pend}")

    elif stage == "transfer":
        discovered = [i for i in items if i.discovery_status == "completed" and i.download_url]
        lines.append(f"  Assets ready to upload: {len(discovered)}")
        lines.append(f"  Upload to Google completed: {sum(1 for i in discovered if i.transfer_status == 'completed')}")
        lines.append(f"  Upload failed: {sum(1 for i in discovered if i.transfer_status == 'failed')}")
        tp = sum(1 for i in discovered if i.transfer_status in ("pending", "running"))
        if tp:
            lines.append(f"  Upload pending / in progress: {tp}")
        lines.append(
            f"  Marked skip library step (transfer issue): {sum(1 for i in items if i.create_status == 'skipped')}",
        )
        if transfer_metrics is not None:
            lines.append("  Throughput:")
            lines.extend(_transfer_throughput_lines(transfer_metrics))

    else:
        with_token = [i for i in items if i.transfer_status == "completed" and i.upload_token]
        lines.append(f"  Items with upload token: {len(with_token)}")
        lines.append(f"  Registered in Photos library: {sum(1 for i in items if i.create_status == 'completed')}")
        lines.append(f"  Library registration failed: {sum(1 for i in items if i.create_status == 'failed')}")
        cp = sum(1 for i in with_token if i.create_status in ("pending", "running"))
        if cp:
            lines.append(f"  Library registration pending / in progress: {cp}")
        batches = list(state.batches.values())
        if batches:
            lines.append(
                f"  batchCreate HTTP batches — completed: {sum(1 for b in batches if b.status == 'completed')}, "
                f"failed: {sum(1 for b in batches if b.status == 'failed')}, "
                f"other: {sum(1 for b in batches if b.status not in ('completed', 'failed'))}",
            )
        if batch_create_responses:
            api_ok = sum(1 for batch in batch_create_responses for r in batch.newMediaItemResults if r.mediaItem)
            api_fail = sum(1 for batch in batch_create_responses for r in batch.newMediaItemResults if not r.mediaItem)
            lines.append(f"  API rows this stage return: {api_ok} succeeded, {api_fail} failed")

    lines.append("")
    return "\n".join(lines)


def _format_sync_summary(
    session_id: str,
    state: SessionState,
    responses: list[MediaItemBatchCreateResponse],
    *,
    elapsed_seconds: float,
    transfer_metrics: SyncTransferMetrics,
) -> str:
    """Build a human-readable post-sync summary from persisted state and batch-create responses."""
    lines: list[str] = []
    lines.append(f"Session {session_id}")
    lines.append(f"Capture window: {state.start_date_iso} → {state.end_date_iso}")
    st = state.stages
    lines.append(
        f"Stages: discovery={st.get('discovery', '?')} | "
        f"transfer={st.get('transfer', '?')} | create={st.get('create', '?')}",
    )
    lines.append("")

    items = list(state.items.values())
    total = len(items)
    if total == 0:
        lines.append("No media items in session.")
        lines.append("")
        lines.append("Data transfer (transfer stage):")
        lines.extend(_transfer_throughput_lines(transfer_metrics))
        lines.append("")
        lines.append(_format_execution_time(elapsed_seconds))
        return "\n".join(lines)

    def count(pred: Callable[[ItemState], bool]) -> int:
        return sum(1 for i in items if pred(i))

    in_library = count(lambda i: i.create_status == "completed")
    skipped = count(lambda i: i.create_status == "skipped")
    create_failed = count(lambda i: i.create_status == "failed")
    create_pending = count(lambda i: i.create_status in ("pending", "running"))
    disc_failed = count(lambda i: i.discovery_status == "failed")
    xfer_failed = count(lambda i: i.transfer_status == "failed")
    xfer_pending = count(
        lambda i: i.transfer_status in ("pending", "running") and i.discovery_status == "completed",
    )

    lines.append(f"Media items: {total}")
    lines.append(f"  In Google Photos (registered): {in_library}")
    lines.append(f"  Skipped (no library registration): {skipped}")
    lines.append(f"  Failed — discovery: {disc_failed}")
    lines.append(f"  Failed — transfer: {xfer_failed}")
    lines.append(f"  Failed — create (library): {create_failed}")
    lines.append(f"  Pending / in progress: {create_pending + xfer_pending}")

    api_ok = 0
    api_fail = 0
    for batch in responses:
        for res in batch.newMediaItemResults:
            if res.mediaItem is not None:
                api_ok += 1
            else:
                api_fail += 1
    if responses:
        lines.append("")
        lines.append(f"This run — batchCreate API rows: {api_ok} succeeded, {api_fail} failed")

    failures: list[tuple[str, str, str]] = []
    for it in sorted(items, key=lambda x: x.file_name):
        if it.discovery_status == "failed":
            err = (it.errors.get("discovery") or {}).get("message", "unknown")
            failures.append((it.file_name, "discovery", str(err)))
        elif it.transfer_status == "failed":
            err = (it.errors.get("transfer") or {}).get("message", "unknown")
            failures.append((it.file_name, "transfer", str(err)))
        elif it.create_status == "failed":
            err = (it.errors.get("create") or {}).get("message", "unknown")
            failures.append((it.file_name, "create", str(err)))

    if failures:
        lines.append("")
        lines.append("Failures:")
        max_rows = 50
        for fn, stage, msg in failures[:max_rows]:
            lines.append(f"  {fn}  [{stage}]  {msg}")
        if len(failures) > max_rows:
            lines.append(f"  … and {len(failures) - max_rows} more")

    lines.append("")
    lines.append("Data transfer (transfer stage):")
    lines.extend(_transfer_throughput_lines(transfer_metrics))

    lines.append("")
    lines.append(_format_execution_time(elapsed_seconds))
    return "\n".join(lines)


def _parse_iso_datetime(value: str) -> datetime:
    """Parse an ISO 8601 calendar date or datetime string.

    Args:
        value: String accepted by :meth:`datetime.datetime.fromisoformat`.

    Returns:
        Parsed timezone-naive or aware datetime.

    Raises:
        ValueError: If ``value`` is not a valid ISO string.
    """
    return datetime.fromisoformat(value)


async def _run_sync(
    *,
    cfg: Q2GoogleSettings,
    start: datetime,
    end: datetime,
    credentials: Path,
    token: Path,
    state_dir: Path,
    session_id: str,
    chunk_multiplier: int,
    max_items: int,
    prefer_height: int,
    batch_size: int | None,
    fail_fast: bool | None,
) -> tuple[list[MediaItemBatchCreateResponse], SyncTransferMetrics]:
    """Open GoPro and Google Photos clients and run a full staged sync for one session.

    Returns:
        Batch-create responses from this invocation and transfer-stage byte/time metrics.

    Args:
        cfg: Resolved settings (timeouts, defaults merged from env and CLI).
        start: Capture window start for new sessions (ignored when resuming existing state).
        end: Capture window end for new sessions (ignored when resuming existing state).
        credentials: OAuth client secrets JSON path.
        token: Path to store the user OAuth token.
        state_dir: Root directory for :class:`~q2google.state.local.JsonFileBackend` session files.
        session_id: Stable session key used for load/resume.
        chunk_multiplier: Resumable upload chunk multiplier for :class:`~q2google.photos.GooglePhotosClient`.
        max_items: Maximum media items listed from GoPro cloud.
        prefer_height: Preferred download height for GoPro assets.
        batch_size: Transfer batch size for new sessions; ``None`` uses ``cfg.sync_batch_size``.
        fail_fast: Whether to abort on first error; ``None`` uses ``cfg.fail_fast``.
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

    logging.debug("session_id=%s state_dir=%s", session_id, state_dir.resolve())

    async with (
        AsyncGoProClient(
            max_items=max_items,
            prefer_height=prefer_height,
        ) as gopro,
        GooglePhotosAPI(
            credentials=creds,
            timeout=cfg.google_photos_timeout_seconds,
        ) as google_photos_api,
    ):
        photos = GooglePhotosClient(google_photos_api, chunk_granularity_multiplier=chunk_multiplier)
        state_backend = JsonFileBackend(state_dir)
        syncer = GoProToPhotosSync(gopro, photos, state_backend=state_backend, settings=cfg)

        transfer_metrics = SyncTransferMetrics()

        async def _report_stage(
            st: StageKey,
            st_state: SessionState,
            responses: list[MediaItemBatchCreateResponse] | None,
        ) -> None:
            typer.echo(
                _format_stage_operations_summary(
                    st,
                    st_state,
                    responses,
                    transfer_metrics=transfer_metrics if st == "transfer" else None,
                ),
            )

        responses = await syncer.sync_date_range(
            start_date=start,
            end_date=end,
            session_id=session_id,
            batch_size=batch_size,
            fail_fast=fail_fast,
            on_stage_complete=_report_stage,
            transfer_metrics=transfer_metrics,
        )
        return responses, transfer_metrics


@app.command("sync")
def sync_command(
    start_date: str = typer.Option(
        ...,
        "--start-date",
        help="Capture window start (ISO date or datetime, e.g. 2026-01-08).",
    ),
    end_date: str = typer.Option(
        ...,
        "--end-date",
        help="Capture window end (ISO date or datetime, e.g. 2026-01-09).",
    ),
    credentials: Path | None = typer.Option(
        None,
        "--credentials",
        help="Google OAuth client secrets JSON; default from Q2GOOGLE_CREDENTIALS_PATH / settings.",
    ),
    token: Path | None = typer.Option(
        None,
        "--token",
        help="Authorized user token path; default from Q2GOOGLE_TOKEN_PATH / settings.",
    ),
    state_dir: Path | None = typer.Option(
        None,
        "--state-dir",
        help="JSON session root; default from Q2GOOGLE_STATE_DIR / settings.",
    ),
    session_id: str | None = typer.Option(
        None,
        "--session-id",
        help="Resume id; default Q2GOOGLE_SESSION_ID / settings, else a new UUID.",
    ),
    chunk_multiplier: int | None = typer.Option(
        None,
        "--chunk-multiplier",
        help="Resumable upload chunk multiplier; default from settings.",
    ),
    max_items: int | None = typer.Option(
        None,
        "--max-items",
        help="GoPro list_media_items cap; default from settings.",
    ),
    prefer_height: int | None = typer.Option(
        None,
        "--prefer-height",
        help="Preferred GoPro download height; default from settings.",
    ),
    batch_size: int | None = typer.Option(
        None,
        "--batch-size",
        help="Transfer batch size for new sessions; default from settings.",
    ),
    fail_fast: bool | None = typer.Option(
        None,
        "--fail-fast/--no-fail-fast",
        help="Fail-fast mode; default from Q2GOOGLE_FAIL_FAST / settings.",
    ),
    log_level: str | None = typer.Option(
        None,
        "--log-level",
        help="Logging level (overrides quiet default); e.g. DEBUG, INFO.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Log q2google at INFO (libraries stay quieter unless --log-level DEBUG).",
    ),
) -> None:
    """Run discovery, transfer, and create stages for the given capture window.

    Merges Typer options with :func:`~q2google.config.get_settings`, starts logging, resolves the
    session id, and executes :func:`_run_sync` via :func:`asyncio.run`.

    Args:
        start_date: ISO start of the GoPro capture window (required).
        end_date: ISO end of the GoPro capture window (required).
        credentials: OAuth secrets path; defaults from settings when omitted.
        token: User token path; defaults from settings when omitted.
        state_dir: Session JSON directory; defaults from settings when omitted.
        session_id: Explicit resume id; otherwise settings or a new UUID.
        chunk_multiplier: Upload chunk multiplier; defaults from settings when omitted.
        max_items: GoPro listing cap; defaults from settings when omitted.
        prefer_height: Preferred asset height; defaults from settings when omitted.
        batch_size: New-session transfer batch size; defaults from settings when omitted.
        fail_fast: Overrides settings when ``True`` or ``False``; ``None`` uses settings.
        log_level: Explicit logging level; when omitted the CLI defaults to quiet (WARNING).
        verbose: When True and ``log_level`` is omitted, sets INFO for ``q2google`` loggers.
    """
    cfg = get_settings()

    _configure_cli_logging(explicit_level=log_level, verbose=verbose)

    start = _parse_iso_datetime(start_date)
    end = _parse_iso_datetime(end_date)

    sid = session_id or cfg.session_id or str(uuid.uuid4())

    resolved_state_dir = state_dir if state_dir is not None else cfg.state_dir

    state_backend = JsonFileBackend(resolved_state_dir)
    existing_session = state_backend.load(sid)
    typer.echo(f"Session: {sid}")
    if existing_session is not None:
        typer.echo(f"Capture window: {existing_session.start_date_iso} → {existing_session.end_date_iso}")
    else:
        typer.echo(f"Capture window: {start.isoformat()} → {end.isoformat()}")
    typer.echo("")

    t0 = time.perf_counter()
    responses, transfer_metrics = asyncio.run(
        _run_sync(
            cfg=cfg,
            start=start,
            end=end,
            credentials=credentials if credentials is not None else cfg.credentials_path,
            token=token if token is not None else cfg.token_path,
            state_dir=resolved_state_dir,
            session_id=sid,
            chunk_multiplier=(chunk_multiplier if chunk_multiplier is not None else cfg.chunk_granularity_multiplier),
            max_items=max_items if max_items is not None else cfg.gopro_max_items,
            prefer_height=prefer_height if prefer_height is not None else cfg.gopro_prefer_height,
            batch_size=batch_size,
            fail_fast=fail_fast,
        )
    )
    elapsed = time.perf_counter() - t0

    final_state = state_backend.load(sid)
    if final_state is None:
        typer.secho(
            "Warning: session state file missing after sync; summary unavailable.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        typer.echo("")
        typer.echo("Data transfer (transfer stage):")
        typer.echo("\n".join(_transfer_throughput_lines(transfer_metrics)))
        typer.echo("")
        typer.echo(_format_execution_time(elapsed))
    else:
        typer.echo(
            _format_sync_summary(
                sid, final_state, responses, elapsed_seconds=elapsed, transfer_metrics=transfer_metrics
            )
        )
