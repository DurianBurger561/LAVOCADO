"""Cross-platform locations for LAVOCADO's local application data."""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from pathlib import Path


def default_data_dir(
    system_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the user-specific data directory without creating it."""

    system_name = system_name or platform.system()
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else home

    override = environ.get("LAVOCADO_DATA_DIR")
    if override:
        return Path(override).expanduser()

    if system_name == "Windows":
        local_app_data = environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else home / "AppData" / "Local"
        return base / "LAVOCADO"

    if system_name == "Darwin":
        return home / "Library" / "Application Support" / "LAVOCADO"

    xdg_data_home = environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else home / ".local" / "share"
    return base / "lavocado"


def default_database_path(**kwargs: object) -> Path:
    """Return the default SQLite database path for this user."""

    return default_data_dir(**kwargs) / "events.db"
