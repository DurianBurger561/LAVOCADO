"""GUI-neutral overlay backend contract."""

from __future__ import annotations

from typing import Protocol

from app.platforms.capture import MonitorInfo


class OverlayBackend(Protocol):
    @property
    def is_visible(self) -> bool: ...

    def show(
        self,
        monitor: MonitorInfo,
    ) -> None: ...

    def hide(self) -> None: ...

    def close(self) -> None: ...
