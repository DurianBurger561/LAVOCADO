"""Non-blocking AI meditation panel rendered above the existing overlay copy."""

from __future__ import annotations

from pathlib import Path
from threading import Lock, Thread
from typing import Any, Callable

from app import config
from app.intervention.llm import (
    LLMClient,
    MeditationContext,
    PracticeIntro,
    QuestionTurn,
    time_of_day,
    today_trigger_count,
)
from app.intervention.llm_status import LLMStatus
from app.platforms.capture import MonitorInfo
from app.ui.overlay.macos_tk import activate_macos_overlay_window
from app.ui.overlay.widgets import FlatAction

# Catppuccin Mocha keeps the intervention panel visually aligned with the
# rest of the overlay while reserving cyan-like accents for active states.
PANEL_BG = config.OVERLAY_BG
PANEL_SURFACE = "#181825"
PANEL_INPUT = "#313244"
PANEL_BORDER = "#45475a"
PANEL_CYAN = "#89b4fa"
PANEL_MINT = "#a6e3a1"
PANEL_TEXT = "#cdd6f4"
PANEL_MUTED = "#a6adc8"
PANEL_ROSE = "#f38ba8"

# The panel speaks the same language as the companion inside it.
PANEL_TEXT_PACKS = {
    "en": {
        "link": "AI / LLM MEDITATION LINK",
        "title": "Adaptive meditation",
        "privacy": "PRIVATE / IN-MEMORY",
        "next_step": "NEXT STEP",
        "send": "SEND",
        "exit": "EXIT",
        "start": "START TYPING MEDITATION",
        "close": "CLOSE PRACTICE",
        "online": "API REPLY RECEIVED",
        "unverified": "API NOT VERIFIED",
        "requesting": "REQUESTING API",
        "offline": "LOCAL GUIDANCE",
        "failed": "API FAILED / LOCAL",
        "temporary": "this conversation is never saved",
        "opening": (
            "Let's talk for a bit first, then I will guide you through a typing "
            "meditation. You can start or leave at any time."
        ),
        "preparing": "preparing a gentle check-in",
        "answer_or_start": "Answer briefly, or start whenever you are ready.",
        "reading": "Reading what you said…",
        "opening_practice": "Let's slow down. I am thinking about how to guide this typing meditation…",
        "opening_status": "Reading what you said, then opening the practice…",
        "type_or_exit": "Type the line if it feels useful, or leave at any time.",
        "next_line": "Thinking of the next gentle line…",
        "closing_prompt": "Letting this minute end slowly…",
        "closing_status": "Finding a calm closing…",
        "stop_when_ready": "You can stop here whenever you feel ready.",
        "closing_fallback": (
            "That is the end of this typing meditation. You just gave yourself a "
            "minute. One small, kind thing next is enough."
        ),
        "start_words": ("start", "begin", "ready", "skip"),
        "speaker_ai": "AI",
        "speaker_you": "YOU",
        "speaker_system": "SYSTEM",
        "speaker_local": "LOCAL",
    },
    "zh": {
        "link": "AI 冥想连接",
        "title": "自适应冥想",
        "privacy": "仅存内存 / 不会保存",
        "next_step": "下一句",
        "send": "发送",
        "exit": "退出",
        "start": "开始打字冥想",
        "close": "结束练习",
        "online": "本轮 API 已响应",
        "unverified": "API 尚未验证",
        "requesting": "正在请求 API",
        "offline": "本地引导",
        "failed": "API 失败 / 本地引导",
        "temporary": "这次对话不会被保存",
        "opening": "先聊两句，然后我陪你做一段打字冥想。你随时可以直接开始，或者退出。",
        "preparing": "正在准备一个温和的开场",
        "answer_or_start": "简单回答就好，也可以随时开始。",
        "reading": "正在读你说的话…",
        "opening_practice": "让我们慢一点。我在想怎么陪你做这段打字冥想…",
        "opening_status": "正在读你说过的话，准备开始练习…",
        "type_or_exit": "想打就把它打出来，也可以随时退出。",
        "next_line": "正在想下一句…",
        "closing_prompt": "让这一分钟慢慢结束…",
        "closing_status": "正在温和地收尾…",
        "stop_when_ready": "你随时可以在这里结束。",
        "closing_fallback": (
            "这段打字冥想到这里。你已经为自己留出了一分钟，"
            "接下来做一件温和的小事就好。"
        ),
        "start_words": ("开始", "够了", "start", "begin"),
        "speaker_ai": "AI",
        "speaker_you": "你",
        "speaker_system": "系统",
        "speaker_local": "本地引导",
    },
}


def panel_words(language: str) -> dict[str, Any]:
    """Panel chrome in the companion's language, falling back to English."""

    return PANEL_TEXT_PACKS.get(language, PANEL_TEXT_PACKS["en"])


class MeditationChatPanel:
    """A fixed top panel that keeps the existing intervention content below it."""

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
        self._client = client or LLMClient.from_environment(data_dir)
        self._words = panel_words(self._client.language)
        self._context = MeditationContext(today_trigger_count(data_dir), time_of_day())
        self._request_token = 0
        self._request_lock = Lock()
        self._response_status: LLMStatus | None = None
        self._closed = False
        self._phase = "questions"
        self._questions_asked = 0
        self._conversation: list[tuple[str, str]] = []
        self._history: list[tuple[str, str]] = []
        self._round_index = 0
        self._panel_width = max(520, min(920, monitor.width - 120))
        self._panel_height = max(320, min(390, monitor.height - 520))
        self._top_margin = 28
        self._mode_label = (
            self._words["unverified"] if self._client.configured else self._words["offline"]
        )
        self._reply_source = "LOCAL"
        self._last_failure = ""

        self._frame = tk.Frame(
            root,
            width=self._panel_width,
            height=self._panel_height,
            background=PANEL_BG,
            highlightbackground=PANEL_BORDER,
            highlightcolor=PANEL_BORDER,
            highlightthickness=1,
        )
        self._frame.grid_propagate(False)
        self._frame.columnconfigure(0, weight=1)
        # Reserve the input and actions at their requested heights; only the
        # transcript gives up vertical space on shorter displays.
        self._frame.rowconfigure(4, weight=1, minsize=40)
        self._frame.place(
            relx=0.5,
            rely=0,
            y=self._top_margin,
            anchor="n",
        )

        header = tk.Frame(self._frame, background=PANEL_BG)
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(13, 0))
        tk.Label(
            header,
            text=self._words["link"],
            background=PANEL_BG,
            foreground=PANEL_CYAN,
            font=("Arial", 9, "bold"),
            anchor="w",
        ).pack(side="left")
        self._mode = tk.Label(
            header,
            text=self._mode_label,
            background=PANEL_SURFACE,
            foreground=PANEL_MUTED,
            font=("Arial", 8, "bold"),
            padx=8,
            pady=3,
        )
        self._mode.pack(side="right")

        title_row = tk.Frame(self._frame, background=PANEL_BG)
        title_row.grid(row=1, column=0, sticky="ew", padx=18, pady=(4, 0))
        tk.Label(
            title_row,
            text=self._words["title"],
            background=PANEL_BG,
            foreground=PANEL_TEXT,
            font=("Arial", 16, "bold"),
            anchor="w",
        ).pack(side="left")
        tk.Label(
            title_row,
            text=self._words["privacy"],
            background=PANEL_BG,
            foreground=PANEL_MUTED,
            font=("Arial", 8, "bold"),
            anchor="e",
        ).pack(side="right")

        tk.Frame(self._frame, height=1, background=PANEL_BORDER).grid(
            row=2, column=0, sticky="ew", padx=18, pady=(8, 8)
        )
        self._status = tk.Label(
            self._frame,
            text="",
            background=PANEL_BG,
            foreground=PANEL_MUTED,
            font=("Arial", 9),
            anchor="w",
            justify="left",
            wraplength=self._panel_width - 40,
        )
        self._status.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 6))

        self._transcript = tk.Text(
            self._frame,
            height=6,
            width=70,
            background=PANEL_SURFACE,
            foreground=PANEL_TEXT,
            insertbackground=PANEL_TEXT,
            relief="flat",
            highlightbackground=PANEL_BORDER,
            highlightthickness=1,
            wrap="word",
            state="disabled",
            padx=10,
            pady=6,
            font=("Arial", 10),
        )
        self._transcript.grid(row=4, column=0, sticky="nsew", padx=18, pady=(0, 8))
        self._transcript.tag_configure("speaker_ai", foreground=PANEL_CYAN, font=("Arial", 9, "bold"))
        self._transcript.tag_configure("speaker_user", foreground=PANEL_MINT, font=("Arial", 9, "bold"))
        self._transcript.tag_configure("speaker_system", foreground=PANEL_MUTED, font=("Arial", 9, "bold"))

        prompt_row = tk.Frame(
            self._frame,
            background=PANEL_BG,
            highlightbackground=PANEL_BORDER,
            highlightthickness=1,
        )
        prompt_row.grid(row=5, column=0, sticky="ew", padx=18, pady=(0, 7))
        tk.Label(
            prompt_row,
            text=self._words["next_step"],
            background=PANEL_BG,
            foreground=PANEL_CYAN,
            font=("Arial", 8, "bold"),
            anchor="w",
        ).pack(side="left", padx=(8, 10), pady=7)
        self._prompt = tk.Label(
            prompt_row,
            text="",
            background=PANEL_BG,
            foreground=PANEL_TEXT,
            font=("Arial", 10, "bold"),
            justify="left",
            anchor="w",
            wraplength=max(260, self._panel_width - 150),
        )
        self._prompt.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=6)

        self._entry = tk.Entry(
            self._frame,
            width=70,
            background=PANEL_INPUT,
            foreground=PANEL_TEXT,
            insertbackground=PANEL_TEXT,
            relief="flat",
            highlightbackground=PANEL_BORDER,
            highlightcolor=PANEL_CYAN,
            highlightthickness=1,
            font=("Arial", 11),
        )
        self._entry.grid(row=6, column=0, sticky="ew", padx=18, pady=(0, 8), ipady=8)
        self._entry.configure(
            insertwidth=2,
            selectbackground=PANEL_CYAN,
            selectforeground="#11111b",
            takefocus=True,
        )
        self._entry.bind("<ButtonRelease-1>", self._focus_entry, add="+")
        self._entry.bind("<Return>", self._submit_from_event)
        self._entry.bind("<Control-Return>", self._submit_from_event)
        self._entry.bind("<Command-Return>", self._submit_from_event)
        actions = tk.Frame(self._frame, background=PANEL_BG)
        actions.grid(row=7, column=0, sticky="ew", padx=18, pady=(0, 7))
        self._send_button = FlatAction(
            tk,
            actions,
            text=self._words["send"],
            command=self._submit,
            background=PANEL_CYAN,
            foreground="#11111b",
            activebackground="#b4befe",
            disabledbackground=PANEL_SURFACE,
            disabledforeground=PANEL_MUTED,
            font=("Arial", 9, "bold"),
            padx=12,
            pady=4,
        )
        self._send_button.pack(side="right", padx=(6, 0))
        self._start_button = FlatAction(
            tk,
            actions,
            text=self._words["start"],
            command=self._start_practice,
            background="#1e3a35",
            foreground=PANEL_MINT,
            activebackground="#254a42",
            disabledbackground=PANEL_SURFACE,
            disabledforeground=PANEL_MUTED,
            font=("Arial", 9, "bold"),
            padx=10,
            pady=4,
        )
        self._start_button.pack(side="left")

        self._exit_button = FlatAction(
            tk,
            actions,
            text=self._words["exit"],
            command=self._on_exit,
            background=PANEL_BG,
            foreground=PANEL_ROSE,
            activebackground="#30202a",
            disabledbackground=PANEL_SURFACE,
            disabledforeground=PANEL_ROSE,
            font=("Arial", 9, "bold"),
            padx=10,
            pady=4,
        )
        self._exit_button.pack(side="right", padx=(0, 4))

        self._append("SYSTEM", f"{self._mode_label} / {self._words['temporary']}")
        self._append("SYSTEM", self._words["opening"])
        self._set_busy(True, self._words["preparing"])
        self._request_question()

    @property
    def layout_bottom(self) -> int:
        return self._top_margin + self._panel_height

    def close(self) -> None:
        self._closed = True
        self._request_token += 1
        try:
            self._frame.destroy()
        except Exception:
            pass

    def _request_question(self) -> None:
        self._phase = "questions_loading"
        self._run_async(
            self._client.generate_question,
            self._context,
            self._conversation,
            on_done=self._receive_question,
            on_failed=self._question_failed,
        )

    def _question_failed(self) -> None:
        self._receive_question(
            self._client.fallback_turn(self._context, self._conversation)
        )

    def _receive_question(self, turn: QuestionTurn) -> None:
        self._apply_reply_status()
        self._phase = "questions"
        # The reflection and the question travel together, so later turns can
        # see what the companion already said back.
        spoken = f"{turn.reflection}\n{turn.question}".strip()
        self._conversation.append(("assistant", spoken))
        self._append(self._reply_source, spoken)
        if turn.enough:
            self._start_practice()
            return
        self._questions_asked += 1
        self._prompt.configure(text=turn.question or self._words["answer_or_start"])
        self._set_busy(False, self._words["answer_or_start"])
        self._start_button.configure(state="normal", text=self._words["start"])
        self._focus_entry()

    def _start_practice(self) -> None:
        if self._closed or self._phase in {"practice_loading", "practice"}:
            return
        self._phase = "practice_loading"
        self._prompt.configure(text=self._words["opening_practice"])
        self._set_busy(True, self._words["opening_status"])
        self._start_button.configure(state="disabled")
        self._run_async(
            self._client.generate_practice_intro,
            self._context,
            self._conversation,
            on_done=self._receive_practice_intro,
            on_failed=self._intro_failed,
        )

    def _intro_failed(self) -> None:
        self._receive_practice_intro(
            self._client.fallback_intro(self._context, self._conversation)
        )

    def _receive_practice_intro(self, intro: PracticeIntro) -> None:
        self._apply_reply_status()
        self._conversation.append(("assistant", intro.invitation))
        self._append(self._reply_source, intro.invitation)
        self._receive_practice_line(intro.first_line)

    def _receive_practice_line(self, line: str) -> None:
        self._apply_reply_status()
        self._phase = "practice"
        self._history.append(("assistant", line))
        self._append(self._reply_source, line)
        self._prompt.configure(text=line)
        self._set_busy(False, self._words["type_or_exit"])
        self._start_button.configure(state="disabled")
        self._focus_entry()

    def _submit(self) -> None:
        if self._closed or self._entry.cget("state") == "disabled":
            return
        answer = self._entry.get().strip()[:500]
        if not answer:
            return
        self._entry.delete(0, "end")
        if self._phase == "questions":
            self._append("You", answer)
            if answer.casefold() in self._words["start_words"]:
                self._start_practice()
                return
            self._conversation.append(("user", answer))
            self._set_busy(True, self._words["reading"])
            self._request_question()
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
        self._set_busy(True, self._words["next_line"])
        self._run_async(
            self._client.generate_practice_line,
            self._context,
            self._conversation,
            self._history,
            self._round_index,
            on_done=self._receive_practice_line,
            on_failed=self._practice_line_failed,
        )

    def _practice_line_failed(self) -> None:
        self._receive_practice_line(
            self._client.fallback_practice_line(
                self._context, self._conversation, self._round_index
            )
        )

    def _request_closing(self) -> None:
        self._phase = "closing_loading"
        self._prompt.configure(text=self._words["closing_prompt"])
        self._set_busy(True, self._words["closing_status"])
        self._run_async(
            self._client.generate_closing,
            self._context,
            self._conversation,
            self._history,
            on_done=self._receive_closing,
            on_failed=lambda: self._receive_closing(self._words["closing_fallback"]),
        )

    def _receive_closing(self, line: str) -> None:
        self._apply_reply_status()
        self._phase = "done"
        self._append(self._reply_source, line)
        self._prompt.configure(text=line)
        self._set_busy(False, self._words["stop_when_ready"])
        self._start_button.configure(state="normal", text=self._words["close"])
        self._start_button.configure(command=self._on_exit)

    def _set_busy(self, busy: bool, status: str) -> None:
        if busy and self._client.configured:
            self._mode_label = self._words["requesting"]
            self._mode.configure(text=self._mode_label, foreground=PANEL_CYAN)
        if not busy and self._last_failure:
            status = LLMStatus("fallback", self._last_failure).detail(self._client.language)
        self._status.configure(text=f"{self._mode_label}  /  {status}")
        state = "disabled" if busy else "normal"
        self._entry.configure(state=state)
        self._send_button.configure(state=state)

    def _apply_reply_status(self) -> None:
        status = self._response_status or self._client.status
        remote = status.state == "online"
        self._reply_source = "AI" if remote else "LOCAL"
        key = "online" if remote else "offline" if status.reason == "no_key" else "failed"
        self._mode_label = self._words[key]
        self._mode.configure(
            text=self._mode_label,
            foreground=PANEL_MINT if remote else PANEL_ROSE if key == "failed" else PANEL_MUTED,
        )
        if status.reason and status.reason != self._last_failure:
            self._append("SYSTEM", f"{status.detail(self._client.language)} {self._words['offline']}")
        self._last_failure = status.reason

    def _focus_entry(self, _event: object | None = None) -> None:
        if self._closed or self._entry.cget("state") == "disabled":
            return
        activate_macos_overlay_window(self._root)
        self._entry.focus_set()

    def _append(self, speaker: str, text: str) -> None:
        self._transcript.configure(state="normal")
        tag = {
            "AI": "speaker_ai",
            "You": "speaker_user",
            "SYSTEM": "speaker_system",
        }.get(speaker, "speaker_system")
        label = {
            "AI": self._words["speaker_ai"],
            "You": self._words["speaker_you"],
            "SYSTEM": self._words["speaker_system"],
            "LOCAL": self._words["speaker_local"],
        }.get(speaker, speaker)
        self._transcript.insert("end", f"{label}  ", tag)
        self._transcript.insert("end", f"{text}\n\n")
        self._transcript.see("end")
        self._transcript.configure(state="disabled")

    def _submit_from_event(self, _event: object) -> str:
        self._submit()
        return "break"

    def _run_async(
        self,
        function: Callable[..., Any],
        *args: Any,
        on_done: Callable[[Any], None],
        on_failed: Callable[[], None] | None = None,
    ) -> None:
        self._request_token += 1
        token = self._request_token

        def worker() -> None:
            # Starting practice can supersede an in-flight question. Serialize
            # client calls and carry each outcome with its own reply.
            with self._request_lock:
                if self._closed or token != self._request_token:
                    return
                try:
                    result = function(*args)
                except Exception:
                    self._client.status = LLMStatus("fallback", "unexpected")
                    result = None
                response_status = self._client.status

            def deliver() -> None:
                if self._closed or token != self._request_token:
                    return
                self._response_status = response_status
                if result is not None:
                    on_done(result)
                elif on_failed is not None:
                    on_failed()

            try:
                self._root.after(0, deliver)
            except Exception:
                return

        Thread(target=worker, daemon=True, name="lavocado-meditation-llm").start()
