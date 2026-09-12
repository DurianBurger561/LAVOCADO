"""Full-screen intervention overlay."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import CancelledError, Future
from threading import Event
from typing import Any

from mss import MSS

from app import config
from app.intervention.sequence import (
    InterventionSequence,
    default_intervention_sequence,
)
from app.platforms import PlatformAdapter
from app.vision.monitors import monitor_geometry, select_monitor_index


class Overlay:
    """Show one blocking, always-on-top intervention window."""

    def __init__(
        self,
        platform_adapter: PlatformAdapter,
        monitor_index: int | None = config.MONITOR_INDEX,
        sequence_factory: Callable[
            [], InterventionSequence
        ] = default_intervention_sequence,
        isolate_macos_process: bool = True,
    ) -> None:
        self._root: Any | None = None
        self._platform = platform_adapter
        self._monitor_index = monitor_index
        self._sequence_factory = sequence_factory
        self._sequence: InterventionSequence | None = None
        self._support_message: Future[str] | None = None
        self._dismiss_scheduled = False
        self._isolate_macos_process = (
            isolate_macos_process
            and getattr(platform_adapter, "name", "") == "Darwin"
        )

    @property
    def is_visible(self) -> bool:
        return self._root is not None

    def show(
        self,
        monitor_index: int | None = None,
        support_message: Future[str] | None = None,
        *,
        parent_closed_event: Event | None = None,
        heartbeat_callback: Callable[[], None] | None = None,
    ) -> None:
        """Block the requested screen until the user dismisses the window."""

        if self.is_visible:
            return

        if self._isolate_macos_process:
            from app.vision.overlay_process import show_overlay_process

            show_overlay_process(monitor_index, support_message)
            return

        try:
            import tkinter as tk
        except ModuleNotFoundError as error:
            raise RuntimeError(
                f"Tkinter is required. {self._platform.tkinter_help()}"
            ) from error

        with MSS() as display_capture:
            selected_index = select_monitor_index(
                display_capture.monitors,
                self._monitor_index if monitor_index is None else monitor_index,
            )
            geometry = monitor_geometry(display_capture.monitors[selected_index])

        root = tk.Tk()
        self._root = root
        self._dismiss_scheduled = False
        self._sequence = self._sequence_factory()
        self._support_message = support_message

        root.withdraw()
        root.title("LAVOCADO Protection")
        root.configure(background=config.OVERLAY_BG)
        self._prepare_overlay_window(root)
        root.overrideredirect(True)
        root.geometry(geometry)
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", self.dismiss)
        root.bind("<Escape>", self._dismiss_from_event)
        root.bind("<Return>", self._request_dismiss_from_event)

        container = tk.Frame(root, background=config.OVERLAY_BG)
        container.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(
            container,
            text="LAVOCADO",
            background=config.OVERLAY_BG,
            foreground=config.OVERLAY_BUTTON_TEXT_COLOR,
            font=("Arial", 18, "bold"),
        ).pack(pady=(0, 28))

        title_label = tk.Label(
            container,
            background=config.OVERLAY_BG,
            foreground=config.OVERLAY_TITLE_COLOR,
            font=("Arial", 38, "bold"),
        )
        title_label.pack(pady=(0, 20))

        body_label = tk.Label(
            container,
            background=config.OVERLAY_BG,
            foreground=config.OVERLAY_TEXT_COLOR,
            font=("Arial", 17),
            justify="center",
            wraplength=700,
        )
        body_label.pack(pady=(0, 36))

        dismiss_button = tk.Button(
            container,
            command=self.request_dismiss,
            background=config.OVERLAY_BUTTON_BG,
            foreground=config.OVERLAY_BUTTON_TEXT_COLOR,
            activebackground=config.OVERLAY_TITLE_COLOR,
            activeforeground=config.OVERLAY_BG,
            font=("Arial", 15, "bold"),
            padx=28,
            pady=14,
            relief="flat",
            cursor="hand2",
            takefocus=True,
        )
        dismiss_button.pack()

        tk.Label(
            container,
            text="Visual processing stays on this device.",
            background=config.OVERLAY_BG,
            foreground=config.OVERLAY_TEXT_COLOR,
            font=("Arial", 10),
        ).pack(pady=(28, 0))

        root.deiconify()
        self._render_step(title_label, body_label, dismiss_button)
        root.after_idle(self._bring_to_front)
        if parent_closed_event is not None:
            root.after(
                100,
                lambda: self._watch_parent_process(root, parent_closed_event),
            )
        if heartbeat_callback is not None:
            root.after(0, lambda: self._send_heartbeat(root, heartbeat_callback))

        try:
            root.mainloop()
        finally:
            self._release_overlay_focus()
            self._root = None
            self._sequence = None
            self._support_message = None
            self._dismiss_scheduled = False

    def request_dismiss(self) -> bool:
        """Dismiss only after the guided stages have completed."""

        if self._sequence is not None and not self._sequence.can_dismiss:
            return False
        self.dismiss()
        return True

    def dismiss(self) -> None:
        """Close the overlay and return control to the monitoring service."""

        if self._root is None or self._dismiss_scheduled:
            return

        root = self._root
        self._dismiss_scheduled = True
        root.after(0, lambda: self._finish_dismiss(root))

    def _finish_dismiss(self, root: Any) -> None:
        if self._root is root:
            self._root = None
        self._dismiss_scheduled = False

        try:
            root.withdraw()
        finally:
            try:
                root.quit()
            finally:
                root.destroy()

    def _dismiss_from_event(self, _event: object) -> str:
        self.dismiss()
        return "break"

    def _request_dismiss_from_event(self, _event: object) -> str:
        self.request_dismiss()
        return "break"

    def _release_overlay_focus(self) -> None:
        try:
            self._platform.release_overlay_focus()
        except Exception:
            return None

    def _prepare_overlay_window(self, root: Any) -> None:
        try:
            self._platform.prepare_overlay_window(root)
        except Exception:
            return

    def _watch_parent_process(self, root: Any, parent_closed_event: Event) -> None:
        if self._root is not root:
            return
        if parent_closed_event.is_set():
            self.dismiss()
            return
        root.after(
            100,
            lambda: self._watch_parent_process(root, parent_closed_event),
        )

    def _send_heartbeat(
        self,
        root: Any,
        heartbeat_callback: Callable[[], None],
    ) -> None:
        if self._root is not root:
            return
        try:
            heartbeat_callback()
        except Exception:
            pass
        root.after(1000, lambda: self._send_heartbeat(root, heartbeat_callback))

    def _render_step(
        self,
        title_label: Any,
        body_label: Any,
        dismiss_button: Any,
    ) -> None:
        if self._root is None or self._sequence is None:
            return

        step = self._sequence.current
        title_label.configure(text=step.title)
        body_label.configure(text=step.body)
        dismiss_button.configure(
            text=step.button_label,
            state="normal" if step.can_dismiss else "disabled",
        )

        if step.can_dismiss:
            self._show_support_message(body_label)
            self._bring_to_front(dismiss_button)
        elif step.duration_seconds is not None:
            delay_ms = max(1, round(step.duration_seconds * 1000))
            self._root.after(
                delay_ms,
                lambda: self._advance_step(
                    title_label,
                    body_label,
                    dismiss_button,
                ),
            )

    def _advance_step(
        self,
        title_label: Any,
        body_label: Any,
        dismiss_button: Any,
    ) -> None:
        if self._root is None or self._sequence is None:
            return
        if self._sequence.advance():
            self._render_step(title_label, body_label, dismiss_button)

    def _show_support_message(self, body_label: Any) -> None:
        if self._root is None or self._support_message is None:
            return

        if not self._support_message.done():
            self._root.after(100, lambda: self._show_support_message(body_label))
            return

        try:
            message = self._support_message.result()
        except CancelledError:
            return

        if message:
            body_label.configure(text=message)

    def _bring_to_front(self, dismiss_button: Any | None = None) -> None:
        if self._root is None:
            return
        self._root.lift()
        if getattr(self._platform, "name", "") == "Darwin":
            return
        self._root.focus_force()
        if dismiss_button is not None:
            dismiss_button.focus_set()
