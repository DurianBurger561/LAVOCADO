"""Non-blocking AI meditation panel rendered beside the existing overlay copy."""

from __future__ import annotations

from pathlib import Path
from threading import Thread
from typing import Any, Callable

from app.intervention.llm import (
    LLMClient,
    MeditationContext,
    time_of_day,
    today_trigger_count,
)
from app.platforms.capture import MonitorInfo


class MeditationChatPanel:
    """A fixed side panel that never changes the overlay's centered layout."""

    def __init__(
        self,
        root: Any,
        monitor: MonitorInfo,
        *,
        on_exit: Callable[[], None],
        client: LLMClient | None = None,
        data_dir: Path | None = None,
    ) -> None:
        import tkinter as tk

        self._tk = tk
        self._root = root
        self._on_exit = on_exit
        self._client = client or LLMClient.from_environment()
        self._context = MeditationContext(today_trigger_count(data_dir), time_of_day())
        self._request_token = 0
        self._closed = False
        self._phase = "questions"
        self._questions: list[str] = []
        self._question_index = 0
        self._conversation: list[tuple[str, str]] = []
        self._history: list[tuple[str, str]] = []
        self._round_index = 0
        self._panel_width = max(320, min(410, monitor.width // 4))

        self._frame = tk.Frame(
            root,
            width=self._panel_width,
            height=520,
            background="#181825",
            highlightbackground="#45475a",
            highlightthickness=1,
        )
        self._frame.pack_propagate(False)
        self._frame.place(relx=1.0, rely=0.5, anchor="e", x=-28)

        tk.Label(
            self._frame,
            text="AI companion",
            background="#181825",
            foreground="#89b4fa",
            font=("Arial", 14, "bold"),
            anchor="w",
        ).pack(fill="x", padx=18, pady=(16, 2))
        self._status = tk.Label(
            self._frame,
            text="Preparing a gentle check-in…",
            background="#181825",
            foreground="#a6adc8",
            font=("Arial", 9),
            anchor="w",
        )
        self._status.pack(fill="x", padx=18, pady=(0, 8))

        self._transcript = tk.Text(
            self._frame,
            height=11,
            width=38,
            background="#1e1e2e",
            foreground="#cdd6f4",
            insertbackground="#cdd6f4",
            relief="flat",
            wrap="word",
            state="disabled",
            padx=10,
            pady=8,
            font=("Arial", 10),
        )
        self._transcript.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        self._prompt = tk.Label(
            self._frame,
            text="",
            background="#181825",
            foreground="#f5e0e6",
            font=("Arial", 11, "bold"),
            justify="left",
            anchor="w",
            wraplength=self._panel_width - 36,
        )
        self._prompt.pack(fill="x", padx=18, pady=(0, 8))

        self._entry = tk.Entry(
            self._frame,
            background="#313244",
            foreground="#cdd6f4",
            insertbackground="#cdd6f4",
            relief="flat",
            font=("Arial", 11),
        )
        self._entry.pack(fill="x", padx=18, pady=(0, 8), ipady=7)
        self._entry.bind("<Return>", self._submit_from_event)

        actions = tk.Frame(self._frame, background="#181825")
        actions.pack(fill="x", padx=14, pady=(0, 8))
        self._send_button = tk.Button(
            actions,
            text="Send",
            command=self._submit,
            background="#89b4fa",
            foreground="#11111b",
            activebackground="#b4befe",
            relief="flat",
            cursor="hand2",
            font=("Arial", 10, "bold"),
        )
        self._send_button.pack(side="right", padx=(6, 0))
        self._start_button = tk.Button(
            actions,
            text="Start practice",
            command=self._start_practice,
            background="#313244",
            foreground="#a6e3a1",
            activebackground="#45475a",
            relief="flat",
            cursor="hand2",
            font=("Arial", 10, "bold"),
        )
        self._start_button.pack(side="left")

        self._exit_button = tk.Button(
            self._frame,
            text="Exit overlay",
            command=self._on_exit,
            background="#313244",
            foreground="#f38ba8",
            activebackground="#45475a",
            relief="flat",
            cursor="hand2",
            font=("Arial", 9),
        )
        self._exit_button.pack(fill="x", padx=18, pady=(0, 14))

        self._append("AI", "你可以回答，也可以直接开始练习。随时都能退出。")
        self._set_busy(True, "Preparing a gentle check-in…")
        self._request_questions()

    def close(self) -> None:
        self._closed = True
        self._request_token += 1
        try:
            self._frame.destroy()
        except Exception:
            pass

    def _request_questions(self) -> None:
        self._run_async(
            self._client.generate_questions,
            self._context,
            on_done=self._receive_questions,
        )

    def _receive_questions(self, questions: list[str]) -> None:
        self._questions = questions
        self._question_index = 0
        self._phase = "questions"
        if not questions:
            self._start_practice()
            return
        self._show_question()

    def _show_question(self) -> None:
        question = self._questions[self._question_index]
        self._conversation.append(("assistant", question))
        self._append("AI", question)
        self._prompt.configure(text=question)
        self._set_busy(False, "Answer briefly or start whenever you are ready.")
        self._start_button.configure(state="normal", text="Start practice")
        self._entry.focus_set()

    def _start_practice(self) -> None:
        if self._closed or self._phase == "practice_loading":
            return
        self._phase = "practice_loading"
        self._prompt.configure(text="让我们慢一点。正在准备第一句引导…")
        self._set_busy(True, "Preparing your first line…")
        self._start_button.configure(state="disabled")
        self._run_async(
            self._client.generate_practice_line,
            self._context,
            self._conversation,
            self._history,
            self._round_index,
            on_done=self._receive_practice_line,
        )

    def _receive_practice_line(self, line: str) -> None:
        self._phase = "practice"
        self._history.append(("assistant", line))
        self._append("AI", line)
        self._prompt.configure(text=line)
        self._set_busy(False, "Type the sentence if it feels useful, or exit at any time.")
        self._start_button.configure(state="disabled")
        self._entry.focus_set()

    def _submit(self) -> None:
        if self._closed or self._entry.cget("state") == "disabled":
            return
        answer = self._entry.get().strip()[:500]
        if not answer:
            return
        self._entry.delete(0, "end")
        if self._phase == "questions":
            self._append("You", answer)
            if answer.casefold() in {"开始", "够了", "start", "begin"}:
                self._start_practice()
                return
            self._conversation.append(("user", answer))
            self._question_index += 1
            if self._question_index >= len(self._questions):
                self._start_practice()
                return
            self._show_question()
            return
        if self._phase != "practice":
            return
        self._append("You", answer)
        self._history.append(("user", answer))
        self._round_index += 1
        if self._round_index >= 5:
            self._request_closing()
            return
        self._phase = "practice_loading"
        self._set_busy(True, "Thinking of the next gentle line…")
        self._run_async(
            self._client.generate_practice_line,
            self._context,
            self._conversation,
            self._history,
            self._round_index,
            on_done=self._receive_practice_line,
        )

    def _request_closing(self) -> None:
        self._phase = "closing_loading"
        self._prompt.configure(text="让这一分钟慢慢结束…")
        self._set_busy(True, "Finding a calm closing…")
        self._run_async(
            self._client.generate_closing,
            self._context,
            self._conversation,
            self._history,
            on_done=self._receive_closing,
        )

    def _receive_closing(self, line: str) -> None:
        self._phase = "done"
        self._append("AI", line)
        self._prompt.configure(text=line)
        self._set_busy(False, "You can stop here whenever you feel ready.")
        self._start_button.configure(state="normal", text="Close practice")
        self._start_button.configure(command=self._on_exit)

    def _set_busy(self, busy: bool, status: str) -> None:
        self._status.configure(text=status)
        state = "disabled" if busy else "normal"
        self._entry.configure(state=state)
        self._send_button.configure(state=state)

    def _append(self, speaker: str, text: str) -> None:
        self._transcript.configure(state="normal")
        self._transcript.insert("end", f"{speaker}\n{text}\n\n")
        self._transcript.see("end")
        self._transcript.configure(state="disabled")

    def _submit_from_event(self, _event: object) -> str:
        self._submit()
        return "break"

    def _run_async(self, function: Callable[..., Any], *args: Any, on_done: Callable[[Any], None]) -> None:
        self._request_token += 1
        token = self._request_token

        def worker() -> None:
            try:
                result = function(*args)
            except Exception:
                result = None

            def deliver() -> None:
                if self._closed or token != self._request_token:
                    return
                if result is not None:
                    on_done(result)

            try:
                self._root.after(0, deliver)
            except Exception:
                return

        Thread(target=worker, daemon=True, name="lavocado-meditation-llm").start()
