"""Create one platform adapter for each LAVOCADO process."""

from __future__ import annotations

import platform
from pathlib import Path

from app.platforms.base import (
    Environment,
    PlatformAdapter,
    UnsupportedPlatformError,
    WindowInfo,
)
from app.platforms.linux import LinuxPlatform
from app.platforms.macos import MacOSPlatform
from app.platforms.windows import WindowsPlatform

SUPPORTED_SYSTEMS = frozenset(
    {WindowsPlatform.name, MacOSPlatform.name, LinuxPlatform.name}
)


def create_platform_adapter(
    system_name: str | None = None,
    *,
    environ: Environment | None = None,
    home: Path | None = None,
) -> PlatformAdapter:
    """Create the sole operating-system adapter for the current process."""

    current = system_name or platform.system()
    if current == WindowsPlatform.name:
        return WindowsPlatform(environ=environ, home=home)
    if current == MacOSPlatform.name:
        return MacOSPlatform(environ=environ, home=home)
    if current == LinuxPlatform.name:
        return LinuxPlatform(environ=environ, home=home)
    raise UnsupportedPlatformError(
        f"LAVOCADO does not currently support {current or 'this OS'}. "
        "Supported systems: Windows, macOS, and Linux."
    )


__all__ = [
    "SUPPORTED_SYSTEMS",
    "LinuxPlatform",
    "MacOSPlatform",
    "PlatformAdapter",
    "UnsupportedPlatformError",
    "WindowInfo",
    "WindowsPlatform",
    "create_platform_adapter",
]
