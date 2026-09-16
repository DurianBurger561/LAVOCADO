"""Tk implementation of the full-screen intervention overlay."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import Any

from app import config
from app.intervention.sequence import (
    InterventionSequence,
    default_intervention_sequence,
)
from app.platforms.capture import MonitorInfo
from app.ui.overlay.macos_tk import prepare_macos_overlay_window
from app.ui.overlay.widgets import FlatAction

LOGGER = logging.getLogger(__name__)


def tk_geometry(monitor: MonitorInfo) -> str:
    """Position Tk from the capture subsystem's canonical monitor geometry."""

    if monitor.width < 1 or monitor.height < 1:
        raise ValueError("Monitor width and height must be positive")
    return (
        f"{monitor.width}x{monitor.height}"
        f"{monitor.left:+d}{monitor.top:+d}"
    )


def tkinter_help(platform_name: str) -> str:
    if platform_name == "Darwin":
        return "Install a current Python build from python.org with Tcl/Tk support."
    if platform_name == "Windows":
        return "Repair the python.org installation and enable the Tcl/Tk feature."
    return "Install Python with Tcl/Tk support."


class TkOverlayBackend:
    """Show one blocking, always-on-top Tk window on a known monitor."""

    def __init__(
        self,
        platform_name: str,
        sequence_factory: Callable[
            [], InterventionSequence
        ] = default_intervention_sequence,
        data_dir: Path | None = None,
    ) -> None:
        self._root: Any | None = None
        self._platform_name = platform_name
        self._sequence_factory = sequence_factory
        self._data_dir = data_dir
        self._sequence: InterventionSequence | None = None
        self._monitor: MonitorInfo | None = None
        self._dismiss_scheduled = False
        self._ai_panel: Any | None = None
        self._main_container: Any | None = None
        self._exit_button: Any | None = None

    @property
    def is_visible(self) -> bool:
        return self._root is not None

    def show(
        self,
        monitor: MonitorInfo,
        *,
        parent_closed_event: Event | None = None,
        heartbeat_callback: Callable[[], None] | None = None,
    ) -> None:
        """Block the requested screen until the user dismisses the window."""

        if self.is_visible:
            return

        try:
            import tkinter as tk
        except ModuleNotFoundError as error:
            raise RuntimeError(
                f"Tkinter is required. {tkinter_help(self._platform_name)}"
            ) from error

        root = tk.Tk()
        self._root = root
        self._monitor = monitor
        self._dismiss_scheduled = False
        self._sequence = self._sequence_factory()

        root.withdraw()
        root.title("LAVOCADO Protection")
        root.configure(background=config.OVERLAY_BG)
        if self._platform_name == "Darwin":
            prepare_macos_overlay_window(root)
        else:
            root.overrideredirect(True)
        root.geometry(tk_geometry(monitor))
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", self.dismiss)
        root.bind("<Escape>", self._dismiss_from_event)
        root.bind_all("<Escape>", self._dismiss_from_event)
        root.bind("<Return>", self._request_dismiss_from_event)

        container = tk.Frame(root, background=config.OVERLAY_BG)
        container.place(relx=0.5, rely=0.5, anchor="center")
        self._main_container = container

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

        dismiss_button = FlatAction(
            tk,
            container,
            text="",
            command=self.request_dismiss,
            background=config.OVERLAY_BUTTON_BG,
            foreground=config.OVERLAY_BUTTON_TEXT_COLOR,
            activebackground=config.OVERLAY_TITLE_COLOR,
            disabledbackground=config.OVERLAY_BUTTON_BG,
            disabledforeground="#6c7086",
            font=("Arial", 15, "bold"),
            padx=28,
            pady=14,
        )
        dismiss_button.pack()

        tk.Label(
            container,
            text="Visual processing stays on this device.",
            background=config.OVERLAY_BG,
            foreground=config.OVERLAY_TEXT_COLOR,
            font=("Arial", 10),
        ).pack(pady=(28, 0))

        self._exit_button = FlatAction(
            tk,
            root,
            text="Exit",
            command=self.dismiss,
            background=config.OVERLAY_BUTTON_BG,
            foreground="#f38ba8",
            activebackground="#45475a",
            font=("Arial", 10, "bold"),
            disabledbackground=config.OVERLAY_BUTTON_BG,
            disabledforeground="#f38ba8",
            padx=12,
            pady=6,
        )
        self._exit_button.place(relx=1.0, x=-24, y=24, anchor="ne")

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
            self._hide_ai_panel()
            if self._exit_button is not None:
                try:
                    self._exit_button.destroy()
                except Exception:
                    pass
                self._exit_button = None
            try:
                root.unbind_all("<Escape>")
            except Exception:
                pass
            self._root = None
            self._monitor = None
            self._main_container = None
            self._sequence = None
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

    def hide(self) -> None:
        self.dismiss()

    def close(self) -> None:
        self.dismiss()

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
            LOGGER.debug("Overlay heartbeat failed", exc_info=True)
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
        # Advancing to Ready must enable Continue even if optional AI setup
        # fails (including an import error in the model configuration).
        title_label.configure(text=step.title)
        body_label.configure(text=step.body)
        dismiss_button.configure(
            text=step.button_label,
            state="normal" if step.can_dismiss else "disabled",
        )
        if step.name == "ready":
            try:
                self._show_ai_panel()
            except Exception:
                LOGGER.exception("Could not open AI panel; Continue remains available")
                self._place_main_container_center()
            else:
                self._place_main_container_below_panel()
        else:
            self._hide_ai_panel()
            self._place_main_container_center()

        if step.can_dismiss:
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

    def _bring_to_front(self, dismiss_button: Any | None = None) -> None:
        if self._root is None:
            return
        self._root.lift()
        if self._ai_panel is not None:
            return
        if self._platform_name == "Darwin":
            return
        self._root.focus_force()
        if dismiss_button is not None:
            dismiss_button.focus_set()

    def _show_ai_panel(self) -> None:
        if self._ai_panel is not None or self._root is None or self._monitor is None:
            return
        # Unit-test fakes do not own a Tk event loop; production roots do.
        if not callable(getattr(self._root, "mainloop", None)):
            return
        from app.ui.overlay.ai_panel import MeditationChatPanel

        children_before = set(self._root.winfo_children())
        try:
            self._ai_panel = MeditationChatPanel(
                self._root,
                self._monitor,
                on_exit=self.dismiss,
                data_dir=self._data_dir,
            )
        except Exception:
            for child in set(self._root.winfo_children()) - children_before:
                child.destroy()
            raise

    def _place_main_container_below_panel(self) -> None:
        if self._main_container is None or self._ai_panel is None:
            return
        self._main_container.place_configure(
            relx=0.5,
            rely=0,
            x=0,
            y=self._ai_panel.layout_bottom + 30,
            anchor="n",
        )

    def _place_main_container_center(self) -> None:
        if self._main_container is None:
            return
        self._main_container.place_configure(
            relx=0.5,
            rely=0.5,
            x=0,
            y=0,
            anchor="center",
        )

    def _hide_ai_panel(self) -> None:
        if self._ai_panel is None:
            return
        try:
            self._ai_panel.close()
        finally:
            self._ai_panel = None
