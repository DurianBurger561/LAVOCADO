"""Shared contracts for platform-specific desktop adapters."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class UnsupportedPlatformError(RuntimeError):
    """Raised when LAVOCADO is started on an unsupported operating system."""


class ScreenCaptureError(RuntimeError):
    """Raised when the operating system prevents screen capture."""


@dataclass(frozen=True, slots=True)
class WindowInfo:
    """Minimal foreground-window data held in memory for one check."""

    title: str
    app_name: str = ""
    left: int | None = None
    top: int | None = None
    width: int | None = None
    height: int | None = None

    @property
    def center(self) -> tuple[int, int] | None:
        if None in (self.left, self.top, self.width, self.height):
            return None
        assert self.left is not None
        assert self.top is not None
        assert self.width is not None
        assert self.height is not None
        if self.width < 1 or self.height < 1:
            return None
        return self.left + self.width // 2, self.top + self.height // 2


class WindowProvider(Protocol):
    """Read the current platform's foreground-window metadata."""

    def active_window(self) -> WindowInfo | None: ...


class PlatformAdapter(Protocol):
    """All operating-system services used by application code."""

    name: str

    def prepare_environment(self) -> None: ...

    def default_data_dir(self) -> Path: ...

    def get_foreground_window(self) -> WindowInfo | None: ...

    def tkinter_help(self) -> str: ...

    def screen_capture_help(self) -> str: ...

    def prepare_webview_environment(self) -> str | None: ...


def data_dir_override(environ: Mapping[str, str]) -> Path | None:
    """Resolve the shared explicit data-directory override."""

    override = environ.get("LAVOCADO_DATA_DIR")
    return None if not override else Path(override).expanduser()


Environment = MutableMapping[str, str]
