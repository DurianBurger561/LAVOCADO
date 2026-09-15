"""Poll foreground identity and read browser websites off the vision thread."""

from __future__ import annotations

from threading import Condition, Event, Thread

from app.context.browser_registry import BrowserDefinition
from app.context.foreground_service import ForegroundContextService
from app.context.models import (
    ApplicationContext,
    ContextPolicyAction,
    WebsiteContext,
    WebsiteContextState,
)
from app.context.policy.application import ApplicationPolicy
from app.context.store import ForegroundContextStore


class ForegroundContextWorker:
    def __init__(
        self,
        service: ForegroundContextService,
        store: ForegroundContextStore,
        *,
        application_policy: ApplicationPolicy | None = None,
        poll_interval: float = 0.75,
    ) -> None:
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        self._service = service
        self._store = store
        self._application_policy = application_policy or ApplicationPolicy()
        self._poll_interval = poll_interval
        self._stop = Event()
        self._condition = Condition()
        self._pending: tuple[int, ApplicationContext, BrowserDefinition] | None = None
        self._threads: tuple[Thread, Thread] | None = None

    def start(self) -> None:
        if self._threads is not None:
            if self._stop.is_set():
                raise RuntimeError("a stopped context worker cannot be restarted")
            return
        if self._stop.is_set():
            raise RuntimeError("a stopped context worker cannot be restarted")
        poller = Thread(target=self._poll_loop, name="lavocado-context-poll", daemon=True)
        reader = Thread(target=self._read_loop, name="lavocado-website-read", daemon=True)
        self._threads = (poller, reader)
        reader.start()
        # Publish the first foreground application before protection performs
        # its first vision check. This makes an application block rule active
        # immediately instead of waiting for the polling thread's first tick.
        try:
            self.poll_once()
        except Exception:  # noqa: BLE001 - keep protection alive on native errors
            self._store.clear()
        poller.start()

    def stop(self) -> None:
        self._stop.set()
        with self._condition:
            self._pending = None
            self._condition.notify_all()
        self._store.clear()
        for thread in self._threads or ():
            thread.join(timeout=0.2)

    def poll_once(self) -> bool:
        """Refresh the application first; queue at most one website request."""

        if self._stop.is_set():
            return False
        application = self._service.read_application()
        browser = self._service.identify_browser(application)
        app_force_blocked = (
            self._application_policy.evaluate(application)
            is ContextPolicyAction.FORCE_BLOCK
        )
        if self._stop.is_set():
            return False
        generation = self._store.observe_application(
            application,
            browser,
            suppress_website=app_force_blocked,
        )
        with self._condition:
            self._pending = (
                (generation, application, browser)
                if browser and not app_force_blocked
                else None
            )
            if self._pending is not None:
                self._condition.notify()
        return True

    def read_pending_once(self) -> bool:
        """Run one potentially slow accessibility read on the reader thread."""

        with self._condition:
            pending = self._pending
            self._pending = None
        if pending is None or self._stop.is_set():
            return False
        generation, application, browser = pending
        try:
            website = self._service.read_website(application, browser)
        except Exception:  # noqa: BLE001 - native errors may contain private URLs
            # Native error text may include a private URL. Never log it.
            website = WebsiteContext(
                WebsiteContextState.UNKNOWN, browser.family, None, None, 0.0
            )
        if not self._stop.is_set():
            self._store.publish_website(generation, website)
        return True

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:  # noqa: BLE001 - keep foreground polling alive
                self._store.clear()
            self._stop.wait(self._poll_interval)

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            with self._condition:
                while self._pending is None and not self._stop.is_set():
                    self._condition.wait()
            if not self._stop.is_set():
                self.read_pending_once()
