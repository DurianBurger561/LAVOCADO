"""Local dashboard for controlling protection and viewing event history."""

from __future__ import annotations

from datetime import datetime

from app import config
from app.intervention.recorder import EventRecorder
from app.platforms import PlatformAdapter
from app.ui.controller import ProtectionController, ProtectionStatus


def event_to_row(event) -> tuple[str, ...]:
    """Convert a stored event into display-only values."""

    occurred_at = datetime.fromisoformat(event.occurred_at)
    if occurred_at.tzinfo is not None:
        occurred_at = occurred_at.astimezone()
    timestamp = occurred_at.strftime("%Y-%m-%d %H:%M:%S")
    confidence = "-" if event.confidence is None else f"{event.confidence:.2f}"
    monitor = str(event.monitor_index)
    shown = "Yes" if event.intervention_shown else "No"
    return (
        timestamp,
        event.trigger_type,
        event.label or "-",
        confidence,
        monitor,
        shown,
    )


class Dashboard:
    """Tk dashboard that owns a separate protection process."""

    def __init__(self, root, tk, ttk, recorder=None, controller=None) -> None:
        self.root = root
        self.tk = tk
        self.ttk = ttk
        self.recorder = recorder or EventRecorder()
        self.controller = controller or ProtectionController()
        self._closed = False
        self._message = ""

        self._configure_window()
        self._build_widgets()
        self._refresh()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(1000, self._poll)

    def _configure_window(self) -> None:
        self.root.title("LAVOCADO")
        self.root.geometry("920x560")
        self.root.minsize(720, 420)
        self.root.configure(bg=config.OVERLAY_BG)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

    def _build_widgets(self) -> None:
        header = self.tk.Frame(self.root, bg=config.OVERLAY_BG, padx=24, pady=20)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        self.tk.Label(
            header,
            text="LAVOCADO",
            bg=config.OVERLAY_BG,
            fg=config.OVERLAY_TITLE_COLOR,
            font=("TkDefaultFont", 20, "bold"),
        ).grid(row=0, column=0, sticky="w")

        self.status_label = self.tk.Label(
            header,
            bg=config.OVERLAY_BG,
            fg=config.OVERLAY_TEXT_COLOR,
            font=("TkDefaultFont", 11, "bold"),
        )
        self.status_label.grid(row=0, column=1, padx=24, sticky="w")

        self.start_button = self.ttk.Button(
            header,
            text="Start protection",
            command=self._start,
        )
        self.start_button.grid(row=0, column=2, padx=(0, 8))

        self.stop_button = self.ttk.Button(
            header,
            text="Stop",
            command=self._stop,
        )
        self.stop_button.grid(row=0, column=3)

        content = self.tk.Frame(self.root, bg=config.OVERLAY_BG, padx=24)
        content.grid(row=1, column=0, sticky="nsew", pady=(0, 20))
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)

        self.total_label = self.tk.Label(
            content,
            bg=config.OVERLAY_BG,
            fg=config.OVERLAY_TEXT_COLOR,
            anchor="w",
            font=("TkDefaultFont", 12, "bold"),
        )
        self.total_label.grid(row=0, column=0, sticky="ew")

        self.message_label = self.tk.Label(
            content,
            bg=config.OVERLAY_BG,
            fg=config.OVERLAY_TEXT_COLOR,
            anchor="w",
        )
        self.message_label.grid(row=1, column=0, sticky="ew", pady=(4, 10))

        columns = ("time", "trigger", "label", "confidence", "monitor", "shown")
        self.tree = self.ttk.Treeview(content, columns=columns, show="headings")
        headings = {
            "time": "Time",
            "trigger": "Trigger",
            "label": "Label",
            "confidence": "Confidence",
            "monitor": "Monitor",
            "shown": "Intervention",
        }
        widths = {
            "time": 165,
            "trigger": 95,
            "label": 220,
            "confidence": 90,
            "monitor": 70,
            "shown": 95,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="center")
        self.tree.column("label", anchor="w")
        self.tree.grid(row=2, column=0, sticky="nsew")

        scrollbar = self.ttk.Scrollbar(
            content,
            orient="vertical",
            command=self.tree.yview,
        )
        scrollbar.grid(row=2, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.ttk.Button(
            content, text="Refresh history", command=self._refresh_events
        ).grid(
            row=3,
            column=0,
            sticky="e",
            pady=(12, 0),
        )

    def _start(self) -> None:
        try:
            if self.controller.start():
                self._message = "Protection started on all detected monitors."
        except OSError as error:
            self._message = f"Could not start protection: {error}"
        self._refresh_status()

    def _stop(self) -> None:
        if self.controller.stop():
            self._message = "Stopping protection safely..."
        self._refresh_status()

    def _refresh_status(self) -> None:
        status = self.controller.status
        detail = f"Protection: {status.value}"
        if status is ProtectionStatus.FAILED:
            detail += f" (exit code {self.controller.last_exit_code})"
        self.status_label.configure(text=detail)
        self.message_label.configure(text=self._message)

        active = status in (ProtectionStatus.RUNNING, ProtectionStatus.STOPPING)
        self.start_button.configure(state="disabled" if active else "normal")
        self.stop_button.configure(
            state="normal" if status is ProtectionStatus.RUNNING else "disabled"
        )

    def _refresh_events(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for event in self.recorder.recent(50):
            self.tree.insert("", "end", values=event_to_row(event))
        self.total_label.configure(
            text=f"Local intervention history ({self.recorder.count()} total)"
        )

    def _refresh(self) -> None:
        self._refresh_status()
        self._refresh_events()

    def _poll(self) -> None:
        if self._closed:
            return
        self._refresh()
        self.root.after(1000, self._poll)

    def close(self) -> None:
        self._closed = True
        self.controller.close()
        self.recorder.close()
        self.root.destroy()


def run_dashboard(platform_adapter: PlatformAdapter) -> None:
    """Open the dashboard on the GUI main thread."""

    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError as error:
        raise RuntimeError(
            "Tkinter is required for the dashboard. On Ubuntu, install python3-tk."
        ) from error

    root = tk.Tk()
    recorder = EventRecorder(platform_adapter.default_data_dir() / "events.db")
    Dashboard(root, tk, ttk, recorder=recorder)
    root.mainloop()
