"""Rich console renderer for q2google CLI output."""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime
from enum import Enum

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.status import Status
from rich.table import Table

from q2google.cli._formatters import MetricsFormatter
from q2google.metrics import SyncTransferMetrics
from q2google.photos import MediaItemBatchCreateResponse
from q2google.state.base import SessionState, StageKey


class OutputFormat(str, Enum):
    """Machine-readable output format selector."""

    rich = "rich"
    tsv = "tsv"
    json = "json"


_STATUS_STYLE: dict[str, str] = {
    "completed": "green",
    "failed": "bold red",
    "pending": "yellow",
    "running": "cyan",
    "skipped": "dim",
}
_STAGE_LABELS: dict[str, str] = {
    "discovery": "Discovery",
    "transfer": "Transfer",
    "create": "Create",
}


def _status_markup(status: str) -> str:
    """Wrap a status string in Rich color markup.

    Args:
        status: Pipeline stage status value.

    Returns:
        Rich markup string like ``"[green]completed[/green]"``.
    """
    style = _STATUS_STYLE.get(status, "white")
    return f"[{style}]{status}[/{style}]"


class SyncPrinter:
    """Rich console renderer for q2google sync output.

    Attributes:
        _fmt: Active output format; controls whether Rich, TSV, or JSON is emitted.
        _console: Primary stdout console.
        _err_console: Stderr console for warnings.
    """

    def __init__(self, *, fmt: OutputFormat = OutputFormat.rich) -> None:
        self._fmt = fmt
        self._console = Console(soft_wrap=True)
        self._err_console = Console(stderr=True, soft_wrap=True)
        self._active_status: Status | None = None

    def print_session_start(
        self,
        session_id: str,
        existing_session: SessionState | None,
        *,
        start: datetime,
        end: datetime,
    ) -> None:
        """Print a session header panel at the beginning of a sync run.

        Suppressed when output format is ``tsv`` or ``json``.

        Args:
            session_id: The session identifier.
            existing_session: Loaded state if resuming; ``None`` for a fresh session.
            start: Capture window start (used only when ``existing_session`` is ``None``).
            end: Capture window end (used only when ``existing_session`` is ``None``).
        """
        if self._fmt != OutputFormat.rich:
            return

        if existing_session is not None:
            window = f"{existing_session.start_date_iso} → {existing_session.end_date_iso}"
        else:
            window = f"{start.isoformat()} → {end.isoformat()}"

        self._console.print(
            Panel(
                f"[bold]Session:[/bold]        [cyan]{session_id}[/cyan]\n[bold]Capture window:[/bold]  {window}",
                title="[bold blue]q2google sync[/bold blue]",
                border_style="blue",
            )
        )

    def start_stage(self, stage: StageKey, *, step: int, total: int) -> None:
        """Start a live spinner indicating that a pipeline stage is in progress.

        No-op when output format is ``tsv`` or ``json`` (machine consumers do not want
        spinner frames in their output). Stops any previously active spinner before
        starting the new one.

        Args:
            stage: The stage key (``"discovery"``, ``"transfer"``, or ``"create"``).
            step: 1-based position of this stage in the pipeline.
            total: Total number of pipeline stages.
        """
        if self._fmt != OutputFormat.rich:
            return
        self._stop_active_status()
        label = _STAGE_LABELS.get(stage, stage.capitalize())
        self._active_status = self._console.status(f"⏳ [bold cyan][{step}/{total}] {label}…[/bold cyan]")
        self._active_status.__enter__()

    def _stop_active_status(self) -> None:
        """Stop and clear the active spinner if one is running."""
        if self._active_status is not None:
            self._active_status.__exit__(None, None, None)
            self._active_status = None

    def print_stage_summary(
        self,
        stage: StageKey,
        state: SessionState,
        batch_create_responses: list[MediaItemBatchCreateResponse] | None,
        *,
        transfer_metrics: SyncTransferMetrics | None = None,
    ) -> None:
        """Print per-item outcomes after one pipeline stage completes.

        Suppressed when output format is ``tsv`` or ``json``; the full summary is
        deferred to :meth:`print_sync_summary` in those modes.

        Args:
            stage: The stage key (``"discovery"``, ``"transfer"``, or ``"create"``).
            state: Session state after the stage.
            batch_create_responses: batchCreate API responses; only relevant for ``"create"`` stage.
            transfer_metrics: Transfer byte/time metrics; only used for the ``"transfer"`` stage.
        """
        self._stop_active_status()

        if self._fmt != OutputFormat.rich:
            return

        stage_labels = _STAGE_LABELS
        title = stage_labels[stage]
        stage_status = state.stages.get(stage, "?")
        table = _make_kv_table()

        if stage == "discovery":
            _add_discovery_rows(table, state)
        elif stage == "transfer":
            _add_transfer_rows(table, state, transfer_metrics)
        else:
            _add_create_rows(table, state, batch_create_responses)

        self._console.print(
            Panel(
                table,
                title=f"[bold]{title}[/bold] — {_status_markup(stage_status)}",
                border_style="blue",
            )
        )

    def print_sync_summary(
        self,
        session_id: str,
        state: SessionState,
        responses: list[MediaItemBatchCreateResponse],
        *,
        elapsed_seconds: float,
        transfer_metrics: SyncTransferMetrics,
    ) -> None:
        """Print a post-sync summary; format depends on ``--output``.

        Args:
            session_id: The session identifier.
            state: Final session state after all stages.
            responses: batchCreate API responses from this invocation.
            elapsed_seconds: Total wall-clock time.
            transfer_metrics: Transfer byte/time metrics from the sync run.
        """
        if self._fmt == OutputFormat.json:
            self._print_summary_json(session_id, state, elapsed_seconds, transfer_metrics)
            return
        if self._fmt == OutputFormat.tsv:
            self._print_summary_tsv(state)
            return
        self._print_summary_rich(
            session_id, state, responses, elapsed_seconds=elapsed_seconds, transfer_metrics=transfer_metrics
        )

    def print_state_missing_warning(
        self,
        transfer_metrics: SyncTransferMetrics,
        elapsed_seconds: float,
    ) -> None:
        """Print a warning when the session state file is missing after sync.

        Args:
            transfer_metrics: Transfer byte/time metrics from the run.
            elapsed_seconds: Total wall-clock time.
        """
        self._err_console.print("[yellow]Warning: session state file missing after sync; summary unavailable.[/yellow]")
        if self._fmt == OutputFormat.json:
            sys.stdout.write(json.dumps({"error": "session state file missing after sync"}) + "\n")
            return
        if self._fmt == OutputFormat.tsv:
            return
        self._print_throughput(transfer_metrics)
        self._console.print(f"[bold]{MetricsFormatter.execution_time(elapsed_seconds)}[/bold]")

    # ------------------------------------------------------------------
    # Private renderers
    # ------------------------------------------------------------------

    def _print_summary_json(
        self,
        session_id: str,
        state: SessionState,
        elapsed_seconds: float,
        transfer_metrics: SyncTransferMetrics,
    ) -> None:
        """Emit the sync summary as a single JSON object on stdout.

        Args:
            session_id: The session identifier.
            state: Final session state.
            elapsed_seconds: Total wall-clock time.
            transfer_metrics: Transfer byte/time metrics.
        """
        payload: dict = {
            "session_id": session_id,
            "capture_window": f"{state.start_date_iso}/{state.end_date_iso}",
            "elapsed_seconds": round(elapsed_seconds, 3),
            "stages": dict(state.stages),
            "items": [i.to_dict() for i in state.items.values()],
            "transfer_metrics": dataclasses.asdict(transfer_metrics),
        }
        sys.stdout.write(json.dumps(payload, indent=2))
        sys.stdout.write("\n")

    def _print_summary_tsv(self, state: SessionState) -> None:
        """Emit the items table as tab-separated values on stdout.

        Args:
            state: Final session state.
        """
        tsv_console = Console(soft_wrap=True, highlight=False, markup=False)
        headers = ["file_name", "discovery_status", "transfer_status", "create_status"]
        tsv_console.print("\t".join(headers))
        for item in sorted(state.items.values(), key=lambda i: i.file_name):
            tsv_console.print(
                f"{item.file_name}\t{item.discovery_status}\t{item.transfer_status}\t{item.create_status}"
            )

    def _print_summary_rich(
        self,
        session_id: str,
        state: SessionState,
        responses: list[MediaItemBatchCreateResponse],
        *,
        elapsed_seconds: float,
        transfer_metrics: SyncTransferMetrics,
    ) -> None:
        """Render the full Rich sync summary.

        Args:
            session_id: The session identifier.
            state: Final session state after all stages.
            responses: batchCreate API responses from this invocation.
            elapsed_seconds: Total wall-clock time.
            transfer_metrics: Transfer byte/time metrics from the sync run.
        """
        st = state.stages
        stages_line = (
            f"discovery={_status_markup(st.get('discovery', '?'))} | "
            f"transfer={_status_markup(st.get('transfer', '?'))} | "
            f"create={_status_markup(st.get('create', '?'))}"
        )

        self._console.print(Rule("[bold blue]Sync Summary[/bold blue]", style="blue"))
        self._console.print(f"[bold]Session:[/bold]        [cyan]{session_id}[/cyan]")
        self._console.print(f"[bold]Capture window:[/bold]  {state.start_date_iso} → {state.end_date_iso}")
        self._console.print(f"[bold]Stages:[/bold]          {stages_line}")

        items = list(state.items.values())
        if not items:
            self._console.print("[dim]No media items in session.[/dim]")
            self._print_throughput(transfer_metrics)
            self._console.print(f"[bold]{MetricsFormatter.execution_time(elapsed_seconds)}[/bold]")
            return

        self._console.print(_build_items_summary_table(items))
        self._print_api_row_summary(responses)
        self._print_failures_table(items)
        self._print_throughput(transfer_metrics)
        self._console.print(f"[bold]{MetricsFormatter.execution_time(elapsed_seconds)}[/bold]")

    def _print_throughput(self, transfer_metrics: SyncTransferMetrics) -> None:
        """Print the transfer throughput section.

        Args:
            transfer_metrics: Transfer metrics to display.
        """
        self._console.print("\n[bold]Data transfer (transfer stage):[/bold]")
        rows = MetricsFormatter.throughput_rows(transfer_metrics)
        if rows:
            for label, value in rows:
                self._console.print(f"  [bold]{label}:[/bold] {value}")
        else:
            self._console.print("  [dim]No transfer activity — stage skipped or idle.[/dim]")
        self._console.print()

    def _print_api_row_summary(self, responses: list[MediaItemBatchCreateResponse]) -> None:
        """Print the batchCreate API row count summary line when responses exist.

        Args:
            responses: batchCreate API responses from this invocation.
        """
        if not responses:
            return
        api_ok = sum(1 for batch in responses for r in batch.newMediaItemResults if r.mediaItem)
        api_fail = sum(1 for batch in responses for r in batch.newMediaItemResults if not r.mediaItem)
        self._console.print(
            f"[bold]This run — batchCreate API rows:[/bold] "
            f"[green]{api_ok}[/green] succeeded, [red]{api_fail}[/red] failed"
        )

    def _print_failures_table(self, items: list) -> None:
        """Print a Rich table of per-item failures sorted by file name.

        Args:
            items: All item states from the session.
        """
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

        if not failures:
            return

        max_rows = 50
        fail_table = Table(title="[bold red]Failures[/bold red]", box=box.SIMPLE_HEAVY, show_header=True)
        fail_table.add_column("File", style="bold")
        fail_table.add_column("Stage", style="yellow")
        fail_table.add_column("Error", style="red")

        for fn, stage, msg in failures[:max_rows]:
            fail_table.add_row(fn, stage, msg)

        self._console.print(fail_table)
        if len(failures) > max_rows:
            self._console.print(f"[dim]… and {len(failures) - max_rows} more[/dim]")


# ---------------------------------------------------------------------------
# Module-private table builder helpers
# ---------------------------------------------------------------------------


def _make_kv_table() -> Table:
    """Build an unstyled key/value Rich table for stage summaries.

    Returns:
        Configured ``Table`` with no header and two columns.
    """
    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    table.add_column("Label", style="bold")
    table.add_column("Value")
    return table


def _add_discovery_rows(table: Table, state: SessionState) -> None:
    """Populate *table* with discovery-stage metric rows.

    Args:
        table: Target table to add rows to.
        state: Session state after the discovery stage.
    """
    items = list(state.items.values())
    failed = sum(1 for i in items if i.discovery_status == "failed")
    pending = sum(1 for i in items if i.discovery_status in ("pending", "running"))

    table.add_row("Items in session", str(len(items)))
    table.add_row(
        "URLs resolved",
        f"[green]{sum(1 for i in items if i.discovery_status == 'completed')}[/green]",
    )
    table.add_row("Discovery failed", f"[red]{failed}[/red]" if failed else "0")
    if pending:
        table.add_row("Discovery pending / in progress", f"[yellow]{pending}[/yellow]")


def _add_transfer_rows(
    table: Table,
    state: SessionState,
    transfer_metrics: SyncTransferMetrics | None,
) -> None:
    """Populate *table* with transfer-stage metric rows.

    Args:
        table: Target table to add rows to.
        state: Session state after the transfer stage.
        transfer_metrics: Transfer byte/time metrics; ``None`` when not available.
    """
    items = list(state.items.values())
    discovered = [i for i in items if i.discovery_status == "completed" and i.download_url]
    failed_xfer = sum(1 for i in discovered if i.transfer_status == "failed")
    pending_xfer = sum(1 for i in discovered if i.transfer_status in ("pending", "running"))

    table.add_row("Assets ready to upload", str(len(discovered)))
    table.add_row(
        "Upload to Google completed",
        f"[green]{sum(1 for i in discovered if i.transfer_status == 'completed')}[/green]",
    )
    table.add_row("Upload failed", f"[red]{failed_xfer}[/red]" if failed_xfer else "0")
    if pending_xfer:
        table.add_row("Upload pending / in progress", f"[yellow]{pending_xfer}[/yellow]")
    table.add_row(
        "Marked skip library step (transfer issue)",
        str(sum(1 for i in items if i.create_status == "skipped")),
    )

    if transfer_metrics is not None:
        rows = MetricsFormatter.throughput_rows(transfer_metrics)
        if rows:
            for label, value in rows:
                table.add_row(label, value)
        else:
            table.add_row("Throughput", "[dim]No transfer activity — stage skipped or idle.[/dim]")


def _add_create_rows(
    table: Table,
    state: SessionState,
    batch_create_responses: list[MediaItemBatchCreateResponse] | None,
) -> None:
    """Populate *table* with create-stage metric rows.

    Args:
        table: Target table to add rows to.
        state: Session state after the create stage.
        batch_create_responses: batchCreate API responses for this stage; may be ``None``.
    """
    items = list(state.items.values())
    with_token = [i for i in items if i.transfer_status == "completed" and i.upload_token]
    failed_create = sum(1 for i in items if i.create_status == "failed")
    pending_create = sum(1 for i in with_token if i.create_status in ("pending", "running"))

    table.add_row("Items with upload token", str(len(with_token)))
    table.add_row(
        "Registered in Photos library",
        f"[green]{sum(1 for i in items if i.create_status == 'completed')}[/green]",
    )
    table.add_row(
        "Library registration failed",
        f"[red]{failed_create}[/red]" if failed_create else "0",
    )
    if pending_create:
        table.add_row("Library registration pending / in progress", f"[yellow]{pending_create}[/yellow]")

    batches = list(state.batches.values())
    if batches:
        completed_b = sum(1 for b in batches if b.status == "completed")
        failed_b = sum(1 for b in batches if b.status == "failed")
        other_b = sum(1 for b in batches if b.status not in ("completed", "failed"))
        table.add_row(
            "batchCreate HTTP batches",
            f"[green]{completed_b}[/green] completed  [red]{failed_b}[/red] failed  {other_b} other",
        )

    if batch_create_responses:
        api_ok = sum(1 for b in batch_create_responses for r in b.newMediaItemResults if r.mediaItem)
        api_fail = sum(1 for b in batch_create_responses for r in b.newMediaItemResults if not r.mediaItem)
        table.add_row(
            "API rows this stage",
            f"[green]{api_ok}[/green] succeeded / [red]{api_fail}[/red] failed",
        )


def _build_items_summary_table(items: list) -> Table:
    """Build a key/value table summarising per-item outcomes across all stages.

    Args:
        items: All item states from the session.

    Returns:
        Populated Rich ``Table`` ready to print.
    """
    table = _make_kv_table()

    in_library = sum(1 for i in items if i.create_status == "completed")
    skipped = sum(1 for i in items if i.create_status == "skipped")
    create_failed = sum(1 for i in items if i.create_status == "failed")
    create_pending = sum(1 for i in items if i.create_status in ("pending", "running"))
    disc_failed = sum(1 for i in items if i.discovery_status == "failed")
    xfer_failed = sum(1 for i in items if i.transfer_status == "failed")
    xfer_pending = sum(
        1 for i in items if i.transfer_status in ("pending", "running") and i.discovery_status == "completed"
    )
    pending_total = create_pending + xfer_pending

    table.add_row("Total media items", str(len(items)))
    table.add_row("In Google Photos (registered)", f"[green]{in_library}[/green]")
    table.add_row("Skipped (no library registration)", str(skipped))
    table.add_row("Failed — discovery", f"[red]{disc_failed}[/red]" if disc_failed else "0")
    table.add_row("Failed — transfer", f"[red]{xfer_failed}[/red]" if xfer_failed else "0")
    table.add_row("Failed — create (library)", f"[red]{create_failed}[/red]" if create_failed else "0")
    if pending_total:
        table.add_row("Pending / in progress", f"[yellow]{pending_total}[/yellow]")

    return table
