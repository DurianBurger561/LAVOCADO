"""Cross-platform locations for LAVOCADO's local application data."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from app.platforms import default_data_dir as platform_data_dir


def default_data_dir(
    system_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the user-specific data directory without creating it."""

    return platform_data_dir(system_name, environ, home)


def default_database_path(**kwargs: object) -> Path:
    """Return the default SQLite database path for this user."""

    return default_data_dir(**kwargs) / "events.db"
