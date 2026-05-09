"""Logging configuration helpers for the q2google CLI."""

from __future__ import annotations

import logging

_NOISY_LOGGER_NAMES: tuple[str, ...] = (
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
