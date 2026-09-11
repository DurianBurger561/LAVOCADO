"""Full-screen intervention overlay."""

from __future__ import annotations

from typing import Any

from mss import MSS

from app import config
from app.platform_support import prepare_desktop_environment, tkinter_help
from app.vision.monitors import monitor_geometry, select_monitor_index


class Overlay:
    """Show one blocking, always-on-top intervention window."""

    def __init__(self, monitor_index: int | None = config.MONITOR_INDEX) -> None:
        self._root: Any | None = None
        self._monitor_index = monitor_index

    @property
    def is_visible(self) -> bool:
        return self._root is not None

    def show(self, monitor_index: int | None = None) -> None:
        """Block the requested screen until the user dismisses the window."""

        if self.is_visible:
            return

        prepare_desktop_environment()

        try:
            import tkinter as tk
        except ModuleNotFoundError as error:
            raise RuntimeError(f"Tkinter is required. {tkinter_help()}") from error

        with MSS() as display_capture:
            selected_index = select_monitor_index(
                display_capture.monitors,
                self._monitor_index if monitor_index is None else monitor_index,
            )
            geometry = monitor_geometry(display_capture.monitors[selected_index])

        root = tk.Tk()
        self._root = root

        root.withdraw()
        root.title("LAVOCADO Protection")
        root.configure(background=config.OVERLAY_BG)
        root.overrideredirect(True)
        root.geometry(geometry)
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", self.dismiss)
        root.bind("<Escape>", self._dismiss_from_event)
        root.bind("<Return>", self._dismiss_from_event)

        container = tk.Frame(root, background=config.OVERLAY_BG)
        container.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(
            container,
            text="LAVOCADO",
            background=config.OVERLAY_BG,
            foreground=config.OVERLAY_BUTTON_TEXT_COLOR,
            font=("Arial", 18, "bold"),
        ).pack(pady=(0, 28))

        tk.Label(
            container,
            text=config.OVERLAY_TITLE_TEXT,
            background=config.OVERLAY_BG,
            foreground=config.OVERLAY_TITLE_COLOR,
            font=("Arial", 38, "bold"),
        ).pack(pady=(0, 20))

        tk.Label(
            container,
            text=config.OVERLAY_BODY_TEXT,
            background=config.OVERLAY_BG,
            foreground=config.OVERLAY_TEXT_COLOR,
            font=("Arial", 17),
            justify="center",
            wraplength=700,
        ).pack(pady=(0, 36))

        dismiss_button = tk.Button(
            container,
            text=config.OVERLAY_BUTTON_LABEL,
            command=self.dismiss,
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
        dismiss_button.bind("<ButtonRelease-1>", self._dismiss_from_event)

        tk.Label(
            container,
            text="Visual processing stays on this device.",
            background=config.OVERLAY_BG,
            foreground=config.OVERLAY_TEXT_COLOR,
            font=("Arial", 10),
        ).pack(pady=(28, 0))

        root.deiconify()
        root.after_idle(lambda: self._bring_to_front(dismiss_button))

        try:
            root.mainloop()
        finally:
            self._root = None

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

    def _bring_to_front(self, dismiss_button: Any | None = None) -> None:
        if self._root is None:
            return
        self._root.lift()
        self._root.focus_force()
        if dismiss_button is not None:
            dismiss_button.focus_set()
