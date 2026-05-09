"""String formatters for durations, byte counts, and transfer rates."""

from __future__ import annotations

from q2google.metrics import SyncTransferMetrics


class MetricsFormatter:
    """Format measurements and transfer metrics into human-readable strings."""

    @staticmethod
    def duration_compact(seconds: float) -> str:
        """Format a duration in seconds as a compact human-readable string.

        Args:
            seconds: Duration in seconds.

        Returns:
            Formatted string like ``"1.23s"``, ``"5m 30.00s"``, or ``"2h 15m 30.00s"``.
        """
        if seconds < 60:
            return f"{seconds:.2f}s"
        minutes, sec = divmod(seconds, 60.0)
        if minutes < 60:
            return f"{int(minutes)}m {sec:.2f}s"
        hours, mins = divmod(int(minutes), 60)
        return f"{hours}h {mins}m {sec:.2f}s"

    @classmethod
    def execution_time(cls, seconds: float) -> str:
        """Format wall-clock duration with an ``Execution time:`` prefix.

        Args:
            seconds: Elapsed seconds.

        Returns:
            String like ``"Execution time: 1m 23.45s"``.
        """
        return f"Execution time: {cls.duration_compact(seconds)}"

    @staticmethod
    def bytes_human(n: int) -> str:
        """Format a byte count using binary IEC labels (KiB, MiB, GiB).

        Args:
            n: Number of bytes.

        Returns:
            Human-readable size string like ``"12.34 MiB"``.
        """
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

    @staticmethod
    def rate_mib_s(bytes_count: int, seconds: float) -> str:
        """Format average throughput as MiB/s.

        Args:
            bytes_count: Total bytes transferred.
            seconds: Duration of the transfer.

        Returns:
            Throughput string like ``"12.34 MiB/s"`` or ``"n/a"`` when undefined.
        """
        if seconds <= 0 or bytes_count <= 0:
            return "n/a"
        mib_per_s = bytes_count / (1024 * 1024) / seconds
        return f"{mib_per_s:.2f} MiB/s"

    @classmethod
    def throughput_rows(cls, m: SyncTransferMetrics) -> list[tuple[str, str]]:
        """Build label/value pairs for transfer throughput display.

        Args:
            m: Transfer metrics from the sync run.

        Returns:
            List of ``(label, value)`` pairs; empty list when no transfer activity occurred.
        """
        if m.bytes_downloaded == 0 and m.bytes_uploaded == 0 and m.seconds_transfer_wall <= 0:
            return []
        return [
            (
                "CDN downloaded",
                f"{cls.bytes_human(m.bytes_downloaded)}"
                f"  (avg {cls.rate_mib_s(m.bytes_downloaded, m.seconds_downloading)})",
            ),
            (
                "Uploaded to Google",
                f"{cls.bytes_human(m.bytes_uploaded)}  (avg {cls.rate_mib_s(m.bytes_uploaded, m.seconds_uploading)})",
            ),
            ("Transfer stage wall time", cls.duration_compact(m.seconds_transfer_wall)),
        ]
