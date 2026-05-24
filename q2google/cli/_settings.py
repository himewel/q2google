"""Merge CLI overrides into :class:`~q2google.config.Q2GoogleSettings` for a sync run."""

from __future__ import annotations

from pathlib import Path

from q2google.config import Q2GoogleSettings


def sync_settings(cfg: Q2GoogleSettings, *, state_dir: Path | None = None) -> Q2GoogleSettings:
    """Return settings with sync-specific CLI overrides applied.

    Args:
        cfg: Base settings from environment and ``.env``.
        state_dir: When set, overrides :attr:`~q2google.config.Q2GoogleSettings.state_dir`
            (used by the filesystem backend when ``state_uri`` is unset).

    Returns:
        Settings instance used for :func:`~q2google.state.build_backend` and the sync pipeline.
    """
    if state_dir is None:
        return cfg
    return cfg.model_copy(update={"state_dir": state_dir})
