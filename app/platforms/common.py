"""Shared contracts for platform-specific desktop adapters."""

from __future__ import annotations

from dataclasses import dataclass
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
