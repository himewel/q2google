"""Typer application and CLI command definitions for q2google."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime
from pathlib import Path

import typer

from q2google.cli._logging import _configure_cli_logging
from q2google.cli._printer import SyncPrinter
from q2google.cli._runner import _run_sync
from q2google.config import get_settings
from q2google.state.local import JsonFileBackend

app = typer.Typer(
    help="q2google — sync GoPro cloud media to Google Photos.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


@app.callback(invoke_without_command=True, no_args_is_help=True)
def _main(ctx: typer.Context) -> None:
    """q2google — sync GoPro cloud media to Google Photos."""


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
        help="Google OAuth client secrets JSON; default from [cyan]Q2GOOGLE_CREDENTIALS_PATH[/cyan] / settings.",
    ),
    token: Path | None = typer.Option(
        None,
        "--token",
        help="Authorized user token path; default from [cyan]Q2GOOGLE_TOKEN_PATH[/cyan] / settings.",
    ),
    state_dir: Path | None = typer.Option(
        None,
        "--state-dir",
        help="JSON session root; default from [cyan]Q2GOOGLE_STATE_DIR[/cyan] / settings.",
    ),
    session_id: str | None = typer.Option(
        None,
        "--session-id",
        help="Resume id; default [cyan]Q2GOOGLE_SESSION_ID[/cyan] / settings, else a new UUID.",
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
        help="Fail-fast mode; default from [cyan]Q2GOOGLE_FAIL_FAST[/cyan] / settings.",
    ),
    log_level: str | None = typer.Option(
        None,
        "--log-level",
        help="Logging level (overrides quiet default); e.g. [bold]DEBUG[/bold], [bold]INFO[/bold].",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Log q2google at INFO (libraries stay quieter unless [bold]--log-level DEBUG[/bold]).",
    ),
) -> None:
    """Run discovery, transfer, and create stages for the given capture window.

    Merges Typer options with :func:`~q2google.config.get_settings`, starts logging, resolves the
    session id, and executes :func:`~q2google.cli._runner._run_sync` via :func:`asyncio.run`.

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

    printer = SyncPrinter()
    printer.print_session_start(sid, existing_session, start=start, end=end)

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
            printer=printer,
        )
    )
    elapsed = time.perf_counter() - t0

    final_state = state_backend.load(sid)
    if final_state is None:
        printer.print_state_missing_warning(transfer_metrics, elapsed)
    else:
        printer.print_sync_summary(
            sid, final_state, responses, elapsed_seconds=elapsed, transfer_metrics=transfer_metrics
        )
