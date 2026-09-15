"""Small Tk widgets used when native controls ignore the overlay palette."""

from __future__ import annotations

from typing import Any, Callable


class FlatAction:
    """A clickable label with deterministic colors on macOS and Windows."""

    def __init__(
        self,
        tk: Any,
        parent: Any,
        *,
        text: str,
        command: Callable[[], None],
        background: str,
        foreground: str,
        activebackground: str,
        disabledbackground: str,
        disabledforeground: str,
        font: tuple[str, int, str] = ("Arial", 9, "bold"),
        padx: int = 12,
        pady: int = 5,
    ) -> None:
        self._command = command
        self._state = "normal"
        self._background = background
        self._foreground = foreground
        self._activebackground = activebackground
        self._disabledbackground = disabledbackground
        self._disabledforeground = disabledforeground
        self._label = tk.Label(
            parent,
            text=text,
            background=background,
            foreground=foreground,
            font=font,
            padx=padx,
            pady=pady,
            cursor="hand2",
        )
        self._label.bind("<Button-1>", self._on_click)
        self._label.bind("<Enter>", self._on_enter)
        self._label.bind("<Leave>", self._on_leave)

    def pack(self, **options: Any) -> None:
        self._label.pack(**options)

    def place(self, **options: Any) -> None:
        self._label.place(**options)

    def configure(self, **options: Any) -> None:
        command = options.pop("command", None)
        if command is not None:
            self._command = command
        state = options.pop("state", None)
        if state is not None:
            self._state = str(state)
            self._apply_state()
        if options:
            self._label.configure(**options)

    def focus_set(self) -> None:
        self._label.focus_set()

    def destroy(self) -> None:
        self._label.destroy()

    def _apply_state(self) -> None:
        enabled = self._state != "disabled"
        self._label.configure(
            background=self._background if enabled else self._disabledbackground,
            foreground=self._foreground if enabled else self._disabledforeground,
            cursor="hand2" if enabled else "",
        )

    def _on_click(self, _event: object) -> None:
        if self._state != "disabled":
            self._command()

    def _on_enter(self, _event: object) -> None:
        if self._state != "disabled":
            self._label.configure(background=self._activebackground)

    def _on_leave(self, _event: object) -> None:
        self._apply_state()
