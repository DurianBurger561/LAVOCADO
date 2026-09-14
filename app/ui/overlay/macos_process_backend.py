"""Isolated macOS overlay backend driven by canonical monitor metadata."""

from __future__ import annotations

from threading import Event

from app.platforms.capture import MonitorInfo
from app.ui.overlay.process import show_overlay_process


class MacOSProcessOverlayBackend:
    """Own the overlay child lifecycle without sharing GUI state with Protection."""

    def __init__(self) -> None:
        self._stop_event = Event()
        self._visible = False

    @property
    def is_visible(self) -> bool:
        return self._visible

    def show(
        self,
        monitor: MonitorInfo,
    ) -> None:
        if self._visible:
            return
        self._stop_event.clear()
        self._visible = True
        try:
            show_overlay_process(
                monitor,
                stop_event=self._stop_event,
            )
        finally:
            self._visible = False

    def hide(self) -> None:
        self._stop_event.set()

    def close(self) -> None:
        self.hide()
