"""Sample the foreground application after the user switches away from Dashboard."""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock, Timer

from app.context.models import ApplicationContext
from app.context.settings import normalize_application_identifier


class ForegroundAppPicker:
    """Own one delayed, privacy-limited foreground application selection."""

    def __init__(
        self,
        read_application: Callable[[], ApplicationContext | None],
        *,
        delay_seconds: float = 4.0,
        timer_factory=Timer,
    ) -> None:
        self._read_application = read_application
        self.delay_seconds = delay_seconds
        self._timer_factory = timer_factory
        self._lock = Lock()
        self._timer = None
        self._generation = 0
        self._status = "idle"
        self._identifier: str | None = None
        self._closed = False

    def begin(self) -> dict[str, object]:
        with self._lock:
            if self._closed:
                return {"status": "unavailable", "identifier": None}
            if self._status == "pending":
                return self._snapshot()
            self._generation += 1
            generation = self._generation
            self._status = "pending"
            self._identifier = None
            timer = self._timer_factory(
                self.delay_seconds, lambda: self._sample(generation)
            )
            timer.daemon = True
            self._timer = timer
            timer.start()
            return self._snapshot()

    def result(self) -> dict[str, object]:
        with self._lock:
            return self._snapshot()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._generation += 1
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._status = "idle"
            self._identifier = None

    def _sample(self, generation: int) -> None:
        try:
            application = self._read_application()
            identifier = (
                normalize_application_identifier(application.identifier)
                if application is not None and application.identifier
                else None
            )
        except Exception:  # noqa: BLE001 - platform reader must not break picker thread
            identifier = None
        with self._lock:
            if self._closed or generation != self._generation:
                return
            self._identifier = identifier
            self._status = "ready" if identifier is not None else "unavailable"
            self._timer = None

    def _snapshot(self) -> dict[str, object]:
        return {
            "status": self._status,
            "identifier": self._identifier,
            "delay_seconds": self.delay_seconds,
        }
