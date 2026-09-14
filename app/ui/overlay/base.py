"""GUI-neutral overlay backend contract."""

from __future__ import annotations

from concurrent.futures import Future
from typing import Protocol

from app.platforms.capture import MonitorInfo


class OverlayBackend(Protocol):
    @property
    def is_visible(self) -> bool: ...

    def show(
        self,
        monitor: MonitorInfo,
        support_message: Future[str] | None = None,
    ) -> None: ...

    def hide(self) -> None: ...

    def close(self) -> None: ...
