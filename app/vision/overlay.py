"""Full-screen intervention overlay."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import CancelledError, Future
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
    ) -> None:
        self._root: Any | None = None
        self._platform = platform_adapter
        self._monitor_index = monitor_index
        self._sequence_factory = sequence_factory
        self._sequence: InterventionSequence | None = None
        self._support_message: Future[str] | None = None

    @property
    def is_visible(self) -> bool:
        return self._root is not None

    def show(
        self,
        monitor_index: int | None = None,
        support_message: Future[str] | None = None,
    ) -> None:
        """Block the requested screen until the user dismisses the window."""

        if self.is_visible:
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
        self._sequence = self._sequence_factory()
        self._support_message = support_message

        root.withdraw()
        root.title("LAVOCADO Protection")
        root.configure(background=config.OVERLAY_BG)
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
        dismiss_button.bind("<ButtonRelease-1>", self._request_dismiss_from_event)

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

        try:
            root.mainloop()
        finally:
            self._root = None
            self._sequence = None
            self._support_message = None

    def request_dismiss(self) -> bool:
        """Dismiss only after the guided stages have completed."""

        if self._sequence is not None and not self._sequence.can_dismiss:
            return False
        self.dismiss()
        return True

    def dismiss(self) -> None:
        """Close the overlay and return control to the monitoring service."""

        if self._root is None:
            return

        root = self._root
        root.destroy()
        self._root = None

    def _dismiss_from_event(self, _event: object) -> str:
        self.dismiss()
        return "break"

    def _request_dismiss_from_event(self, _event: object) -> str:
        self.request_dismiss()
        return "break"

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
        self._root.focus_force()
        if dismiss_button is not None:
            dismiss_button.focus_set()
