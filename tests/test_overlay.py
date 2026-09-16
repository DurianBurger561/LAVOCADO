"""Tests for safe overlay dismissal."""

import unittest
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.intervention.llm import (
    MeditationContext,
    PracticeIntro,
    QuestionTurn,
)
from app.intervention.sequence import InterventionSequence, InterventionStep
from app.intervention.llm_status import LLMStatus
from app.platforms.capture import MonitorInfo
from app.ui.overlay import create_overlay_backend
from app.ui.overlay.ai_panel import MeditationChatPanel, panel_words
from app.ui.overlay.macos_process_backend import MacOSProcessOverlayBackend
from app.ui.overlay.tk_backend import TkOverlayBackend, tk_geometry


class FakeRoot:
    def __init__(self) -> None:
        self.destroy_count = 0
        self.focus_count = 0
        self.quit_count = 0
        self.withdraw_count = 0
        self.scheduled: list[tuple[object, object]] = []
        self._w = "."
        self.tk = FakeTk()

    def destroy(self) -> None:
        self.destroy_count += 1

    def quit(self) -> None:
        self.quit_count += 1

    def withdraw(self) -> None:
        self.withdraw_count += 1

    def after(self, delay_ms: int, callback: object) -> None:
        self.scheduled.append((delay_ms, callback))

    def after_idle(self, callback: object) -> None:
        self.scheduled.append(("idle", callback))

    def lift(self) -> None:
        pass

    def focus_force(self) -> None:
        self.focus_count += 1


class FakeTk:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def call(self, *args: object) -> None:
        self.calls.append(args)


class FakeWidget:
    def __init__(self) -> None:
        self.options: dict[str, object] = {}
        self.focus_count = 0

    def configure(self, **options: object) -> None:
        self.options.update(options)

    def focus_set(self) -> None:
        self.focus_count += 1


class FakeEntryWidget:
    def __init__(self) -> None:
        self.focus_count = 0
        self.text = ""
        self.state = "normal"

    def cget(self, _name: str) -> str:
        return self.state

    def configure(self, **options: object) -> None:
        state = options.get("state")
        if state is not None:
            self.state = str(state)

    def get(self) -> str:
        return self.text

    def delete(self, _first: object, _last: object) -> None:
        self.text = ""

    def focus_set(self) -> None:
        self.focus_count += 1


class FakeTranscript:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def configure(self, **_options: object) -> None:
        return None

    def insert(self, _index: str, text: str, *_tags: str) -> None:
        self.lines.append(text)

    def see(self, _index: str) -> None:
        return None

    @property
    def text(self) -> str:
        return "".join(self.lines)


class ScriptedClient:
    """A stand-in for the LLM client that records what the panel sends it."""

    def __init__(
        self,
        questions: list[QuestionTurn],
        language: str = "zh",
        intro: PracticeIntro | None = None,
    ) -> None:
        self._questions = questions
        self.language = language
        self.configured = True
        self.status = LLMStatus("online")
        self._intro = intro or PracticeIntro(
            invitation="听起来你今天挺累的。我们做一段打字冥想：我给一句，你打一句。",
            first_line="我慢慢吸气，再慢慢呼气。",
        )
        self.question_calls: list[list[tuple[str, str]]] = []
        self.intro_calls: list[list[tuple[str, str]]] = []

    def generate_question(
        self, _context: object, conversation: list[tuple[str, str]]
    ) -> QuestionTurn:
        self.question_calls.append(list(conversation))
        return self._questions[min(len(self.question_calls) - 1, len(self._questions) - 1)]

    def generate_practice_intro(
        self, _context: object, conversation: list[tuple[str, str]]
    ) -> PracticeIntro:
        self.intro_calls.append(list(conversation))
        return self._intro


class OverlayTests(unittest.TestCase):
    def test_factory_selects_supported_backends(self) -> None:
        self.assertIsInstance(create_overlay_backend("Windows"), TkOverlayBackend)
        self.assertIsInstance(
            create_overlay_backend("Darwin"), MacOSProcessOverlayBackend
        )
        with self.assertRaises(ValueError):
            create_overlay_backend("Linux")

    def test_tk_window_uses_passed_monitor_without_display_discovery(self) -> None:
        monitor = MonitorInfo("secondary", 2, -1200, 50, 1200, 900)
        root = Mock()
        widget = Mock()
        tkinter = SimpleNamespace(
            Tk=Mock(return_value=root),
            Frame=Mock(return_value=widget),
            Label=Mock(return_value=widget),
            Button=Mock(return_value=widget),
        )

        with patch.dict("sys.modules", {"tkinter": tkinter}):
            TkOverlayBackend("Windows").show(monitor)

        root.geometry.assert_called_once_with("1200x900-1200+50")

    def test_macos_overlay_uses_an_isolated_process(self) -> None:
        overlay = MacOSProcessOverlayBackend()
        monitor = MonitorInfo("secondary", 2, -1200, 0, 1200, 900)

        with patch("app.ui.overlay.macos_process_backend.show_overlay_process") as show_process:
            overlay.show(monitor)

        show_process.assert_called_once_with(
            monitor, stop_event=overlay._stop_event
        )
        self.assertFalse(overlay.is_visible)

    def test_macos_backend_hide_requests_child_shutdown(self) -> None:
        overlay = MacOSProcessOverlayBackend()

        overlay.hide()

        self.assertTrue(overlay._stop_event.is_set())

    def test_dismiss_destroys_the_window(self) -> None:
        overlay = TkOverlayBackend("Windows")
        root = FakeRoot()
        overlay._root = root

        overlay.dismiss()

        self.assertEqual(root.destroy_count, 0)
        self.assertEqual(root.scheduled[0][0], 0)
        root.scheduled[0][1]()
        self.assertEqual(root.withdraw_count, 1)
        self.assertEqual(root.quit_count, 1)
        self.assertEqual(root.destroy_count, 1)
        self.assertFalse(overlay.is_visible)

    def test_dismiss_only_schedules_once(self) -> None:
        overlay = TkOverlayBackend("Windows")
        root = FakeRoot()
        overlay._root = root

        overlay.dismiss()
        overlay.dismiss()

        self.assertEqual(len(root.scheduled), 1)

    def test_tk_geometry_uses_canonical_monitor_offsets(self) -> None:
        monitor = MonitorInfo("secondary", 2, -1200, 50, 1200, 900)

        self.assertEqual(tk_geometry(monitor), "1200x900-1200+50")

    def test_overlay_closes_when_parent_process_disappears(self) -> None:
        overlay = TkOverlayBackend("Windows")
        root = FakeRoot()
        parent_closed = Event()
        parent_closed.set()
        overlay._root = root

        overlay._watch_parent_process(root, parent_closed)
        root.scheduled[0][1]()

        self.assertEqual(root.destroy_count, 1)
        self.assertFalse(overlay.is_visible)

    def test_overlay_heartbeat_runs_on_tk_event_loop(self) -> None:
        overlay = TkOverlayBackend("Windows")
        root = FakeRoot()
        heartbeat_calls: list[bool] = []
        overlay._root = root

        overlay._send_heartbeat(root, lambda: heartbeat_calls.append(True))

        self.assertEqual(heartbeat_calls, [True])
        self.assertEqual(root.scheduled[0][0], 1000)

    def test_macos_bring_to_front_does_not_force_focus(self) -> None:
        overlay = TkOverlayBackend("Darwin")
        root = FakeRoot()
        button = FakeWidget()
        overlay._root = root

        overlay._bring_to_front(button)

        self.assertEqual(root.focus_count, 0)
        self.assertEqual(button.focus_count, 0)

    def test_ai_panel_bring_to_front_preserves_input_focus_on_windows(self) -> None:
        overlay = TkOverlayBackend("Windows")
        root = FakeRoot()
        button = FakeWidget()
        overlay._root = root
        overlay._ai_panel = object()

        overlay._bring_to_front(button)

        self.assertEqual(root.focus_count, 0)
        self.assertEqual(button.focus_count, 0)

    @patch("app.ui.overlay.ai_panel.activate_macos_overlay_window")
    def test_ai_focus_has_no_delayed_callbacks_after_panel_close(self, _activate) -> None:
        panel = MeditationChatPanel.__new__(MeditationChatPanel)
        panel._closed = False
        panel._root = FakeRoot()
        panel._entry = FakeEntryWidget()
        panel._focus_entry()
        panel._closed = True
        panel._focus_entry()

        self.assertEqual(panel._entry.focus_count, 1)
        self.assertEqual(panel._root.scheduled, [])

    def test_macos_window_keeps_tk_keyboard_activation_enabled(self) -> None:
        root = Mock()
        widget = Mock()
        tkinter = SimpleNamespace(
            Tk=Mock(return_value=root),
            Frame=Mock(return_value=widget),
            Label=Mock(return_value=widget),
        )
        with patch.dict("sys.modules", {"tkinter": tkinter}), patch(
            "app.ui.overlay.tk_backend.prepare_macos_overlay_window"
        ) as prepare:
            TkOverlayBackend("Darwin").show(MonitorInfo("test", 1, 0, 0, 1200, 900))

        prepare.assert_called_once_with(root)
        root.overrideredirect.assert_not_called()

    def test_escape_uses_the_same_dismiss_path(self) -> None:
        overlay = TkOverlayBackend("Windows")
        root = FakeRoot()
        overlay._root = root

        result = overlay._dismiss_from_event(object())

        self.assertEqual(result, "break")
        root.scheduled[0][1]()
        self.assertEqual(root.destroy_count, 1)
        self.assertFalse(overlay.is_visible)

    def test_ai_initialization_error_cannot_strand_the_breathing_stage(self) -> None:
        overlay = TkOverlayBackend("Darwin")
        root = FakeRoot()
        overlay._root = root
        overlay._sequence = InterventionSequence((
            InterventionStep("breathe", "Breathe", "Breathe", "Wait", 1.0),
            InterventionStep("ready", "Ready", "Ready", "Continue", None, True),
        ))
        title, body, button = FakeWidget(), FakeWidget(), FakeWidget()
        overlay._render_step(title, body, button)

        with patch.object(overlay, "_show_ai_panel", side_effect=TypeError("bad AI config")), self.assertLogs(
            "app.ui.overlay.tk_backend", level="ERROR"
        ):
            root.scheduled[0][1]()

        self.assertEqual(title.options["text"], "Ready")
        self.assertEqual(button.options["text"], "Continue")
        self.assertEqual(button.options["state"], "normal")
        self.assertTrue(overlay.request_dismiss())
        root.scheduled[-1][1]()
        self.assertEqual(root.destroy_count, 1)

    def test_failed_ai_panel_cleans_up_its_partial_widgets(self) -> None:
        overlay = TkOverlayBackend("Darwin")
        root = Mock()
        existing, partial_panel = Mock(), Mock()
        root.winfo_children.side_effect = [[existing], [existing, partial_panel]]
        overlay._root = root
        overlay._monitor = MonitorInfo("test", 1, 0, 0, 1200, 900)
        with patch("app.ui.overlay.ai_panel.MeditationChatPanel", side_effect=RuntimeError("panel failed")):
            with self.assertRaisesRegex(RuntimeError, "panel failed"):
                overlay._show_ai_panel()
        partial_panel.destroy.assert_called_once()
        existing.destroy.assert_not_called()
        self.assertIsNone(overlay._ai_panel)

    def test_guided_dismiss_is_locked_until_final_step(self) -> None:
        overlay = TkOverlayBackend("Windows")
        root = FakeRoot()
        overlay._root = root
        overlay._sequence = InterventionSequence(
            (
                InterventionStep("pause", "Pause", "Pause", "Wait", 1.0),
                InterventionStep(
                    "ready",
                    "Ready",
                    "Ready",
                    "Continue",
                    None,
                    True,
                ),
            )
        )

        self.assertFalse(overlay.request_dismiss())
        self.assertEqual(root.destroy_count, 0)

        overlay._sequence.advance()

        self.assertTrue(overlay.request_dismiss())
        root.scheduled[0][1]()
        self.assertEqual(root.destroy_count, 1)

    def test_render_schedules_each_stage_and_enables_final_button(self) -> None:
        overlay = TkOverlayBackend("Windows")
        root = FakeRoot()
        title = FakeWidget()
        body = FakeWidget()
        button = FakeWidget()
        overlay._root = root
        overlay._sequence = InterventionSequence(
            (
                InterventionStep("pause", "Pause", "Pause body", "Wait", 1.0),
                InterventionStep("breathe", "Breathe", "Breathe body", "Wait", 2.0),
                InterventionStep(
                    "ready",
                    "Ready",
                    "Ready body",
                    "Continue",
                    None,
                    True,
                ),
            )
        )

        overlay._render_step(title, body, button)
        self.assertEqual(title.options["text"], "Pause")
        self.assertEqual(button.options["state"], "disabled")
        self.assertEqual(root.scheduled[0][0], 1000)

        root.scheduled[0][1]()
        self.assertEqual(title.options["text"], "Breathe")
        self.assertEqual(root.scheduled[1][0], 2000)

        root.scheduled[1][1]()
        self.assertEqual(title.options["text"], "Ready")
        self.assertEqual(body.options["text"], "Ready body")
        self.assertEqual(button.options["text"], "Continue")
        self.assertEqual(button.options["state"], "normal")
        self.assertEqual(button.focus_count, 1)

    @staticmethod
    def _scripted_panel(client: "ScriptedClient") -> MeditationChatPanel:
        panel = MeditationChatPanel.__new__(MeditationChatPanel)
        panel._closed = False
        panel._root = FakeRoot()
        panel._client = client
        panel._words = panel_words(client.language)
        panel._context = MeditationContext(2, "late_night")
        panel._mode_label = panel._words["online"]
        panel._request_token = 0
        panel._request_lock = Lock()
        panel._response_status = None
        panel._phase = "questions"
        panel._questions_asked = 0
        panel._reply_source = "AI"
        panel._last_failure = ""
        panel._mode = FakeWidget()
        panel._conversation = []
        panel._history = []
        panel._round_index = 0
        panel._entry = FakeEntryWidget()
        panel._transcript = FakeTranscript()
        panel._prompt = FakeWidget()
        panel._status = FakeWidget()
        panel._send_button = FakeWidget()
        panel._start_button = FakeWidget()
        panel._run_async = lambda function, *args, on_done, on_failed=None: on_done(
            function(*args)
        )
        return panel

    @patch("app.ui.overlay.ai_panel.activate_macos_overlay_window")
    def test_each_question_is_written_against_the_previous_answers(self, _activate) -> None:
        client = ScriptedClient(
            [
                QuestionTurn("现在身体是什么感觉？", reflection="谢谢你停下来。"),
                QuestionTurn("那种累是从今天什么时候开始的？", reflection="听起来今天挺沉的。"),
                QuestionTurn(
                    "如果不逼自己，你现在最想要什么？",
                    reflection="下午到现在都撑着，难怪会累。",
                ),
                QuestionTurn("", reflection="你想休息，我们围绕休息来练习。", enough=True),
            ]
        )
        panel = self._scripted_panel(client)

        panel._request_question()
        for answer in ("有点累", "下午开始的", "想睡一会儿"):
            panel._entry.text = answer
            panel._submit()

        self.assertEqual(len(client.question_calls), 4)
        # The second call must already carry the first answer, so the model can
        # follow what the user actually said instead of reciting a script.
        self.assertIn(("user", "有点累"), client.question_calls[1])
        self.assertIn(("user", "下午开始的"), client.question_calls[2])
        self.assertEqual(len(client.intro_calls), 1)

    @patch("app.ui.overlay.ai_panel.activate_macos_overlay_window")
    def test_the_check_in_says_something_back_before_each_question(self, _activate) -> None:
        client = ScriptedClient(
            [QuestionTurn("现在身体是什么感觉？", reflection="谢谢你愿意停一下。")]
        )
        panel = self._scripted_panel(client)

        panel._request_question()

        self.assertIn("谢谢你愿意停一下。", panel._transcript.text)
        self.assertIn("现在身体是什么感觉？", panel._transcript.text)
        # The prompt field holds only the question, so the user knows what to answer.
        self.assertEqual(panel._prompt.options["text"], "现在身体是什么感觉？")
        self.assertEqual(
            panel._conversation, [("assistant", "谢谢你愿意停一下。\n现在身体是什么感觉？")]
        )

    @patch("app.ui.overlay.ai_panel.activate_macos_overlay_window")
    def test_direct_answer_keeps_chat_editable_without_starting_practice(self, _activate) -> None:
        reflection = "I am LAVOCADO's AI companion, here to support a pause."
        client = ScriptedClient([
            QuestionTurn("", reflection=reflection, enough=False),
            QuestionTurn("What feels hardest right now?"),
        ], language="en")
        panel = self._scripted_panel(client)
        panel._conversation.append(("user", "Who are you?"))

        panel._request_question()

        self.assertIn(reflection, panel._transcript.text)
        self.assertEqual(panel._phase, "questions")
        self.assertEqual(panel._prompt.options["text"], panel._words["answer_or_start"])
        self.assertEqual(panel._entry.state, "normal")
        self.assertEqual(panel._start_button.options["state"], "normal")
        self.assertEqual(client.intro_calls, [])

        panel._entry.text = "I want to cry"
        panel._submit()

        self.assertIn(("assistant", reflection), client.question_calls[1])
        self.assertIn(("user", "I want to cry"), client.question_calls[1])
        self.assertEqual(panel._phase, "questions")
        self.assertEqual(client.intro_calls, [])

    @patch("app.ui.overlay.ai_panel.activate_macos_overlay_window")
    def test_the_companion_keeps_asking_until_it_says_it_is_enough(self, _activate) -> None:
        client = ScriptedClient(
            [QuestionTurn(f"问题 {index}") for index in range(10)]
        )
        panel = self._scripted_panel(client)

        panel._request_question()
        for index in range(9):
            panel._entry.text = f"回答 {index}"
            panel._submit()

        # No "enough" arrived, so it must not force a practice after six turns.
        self.assertEqual(panel._phase, "questions")
        self.assertEqual(client.intro_calls, [])
        self.assertEqual(len(client.question_calls), 10)

    @patch("app.ui.overlay.ai_panel.activate_macos_overlay_window")
    def test_practice_opens_with_an_invitation_that_names_typing_meditation(
        self, _activate
    ) -> None:
        client = ScriptedClient([
            QuestionTurn("现在身体是什么感觉？"),
            QuestionTurn("", reflection="听起来你想先休息一下。", enough=True),
        ])
        panel = self._scripted_panel(client)

        panel._request_question()
        panel._entry.text = "有点累"
        panel._submit()

        self.assertIn("打字冥想", panel._transcript.text)
        self.assertEqual(panel._phase, "practice")
        self.assertEqual(panel._prompt.options["text"], "我慢慢吸气，再慢慢呼气。")
        self.assertEqual(panel._history, [("assistant", "我慢慢吸气，再慢慢呼气。")])

    @patch("app.ui.overlay.ai_panel.activate_macos_overlay_window")
    def test_user_can_start_the_practice_before_answering(self, _activate) -> None:
        client = ScriptedClient([QuestionTurn("现在身体是什么感觉？")])
        panel = self._scripted_panel(client)

        panel._request_question()
        panel._entry.text = "开始"
        panel._submit()

        self.assertEqual(len(client.question_calls), 1)
        self.assertEqual(panel._phase, "practice")
        self.assertIn("打字冥想", panel._transcript.text)

    @patch("app.ui.overlay.ai_panel.activate_macos_overlay_window")
    def test_english_panel_shows_english_chrome_and_english_content(self, _activate) -> None:
        client = ScriptedClient(
            [QuestionTurn("How does your body feel right now?"),
             QuestionTurn("", reflection="You feel tired.", enough=True)],
            language="en",
            intro=PracticeIntro(
                invitation="It sounds like you are worn out. Let's do a typing meditation.",
                first_line="I breathe in slowly, and out slowly.",
            ),
        )
        panel = self._scripted_panel(client)

        panel._request_question()
        panel._entry.text = "pretty tired"
        panel._submit()

        self.assertEqual(panel._words["start"], "START TYPING MEDITATION")
        self.assertIn("typing meditation", panel._transcript.text)
        self.assertEqual(panel._prompt.options["text"], "I breathe in slowly, and out slowly.")
        self.assertNotIn("打字冥想", panel._transcript.text)

    @patch("app.ui.overlay.ai_panel.activate_macos_overlay_window")
    def test_english_panel_accepts_english_start_words(self, _activate) -> None:
        client = ScriptedClient(
            [QuestionTurn("How does your body feel right now?")],
            language="en",
            intro=PracticeIntro(
                invitation="Let's do a typing meditation.",
                first_line="I breathe in slowly.",
            ),
        )
        panel = self._scripted_panel(client)

        panel._request_question()
        panel._entry.text = "Start"
        panel._submit()

        self.assertEqual(panel._phase, "practice")
        self.assertEqual(len(client.intro_calls), 1)


    @patch("app.ui.overlay.ai_panel.activate_macos_overlay_window")
    def test_failed_reply_is_labelled_local_and_recovery_is_labelled_ai(self, _activate) -> None:
        client = ScriptedClient([QuestionTurn("How are you?")], language="en")
        panel = self._scripted_panel(client)
        client.status = LLMStatus("fallback", "authentication")
        panel._receive_question(QuestionTurn("Local question"))
        self.assertIn("LOCAL  Local question", panel._transcript.text)
        self.assertIn("401", panel._transcript.text)
        self.assertIn("API FAILED", panel._mode.options["text"])
        self.assertNotIn("AI  Local question", panel._transcript.text)
        client.status = LLMStatus("online")
        panel._receive_question(QuestionTurn("Remote question"))
        self.assertIn("AI  Remote question", panel._transcript.text)
        self.assertEqual(panel._mode.options["text"], "API REPLY RECEIVED")

    @patch("app.ui.overlay.ai_panel.activate_macos_overlay_window")
    def test_ready_summary_is_shown_before_automatic_practice(self, _activate) -> None:
        client = ScriptedClient([QuestionTurn("What happened?")], language="en")
        panel = self._scripted_panel(client)
        panel._conversation.append(("user", "My review is tomorrow and I need rest"))
        panel._receive_question(QuestionTurn("", reflection="The review is weighing on you.", enough=True))
        self.assertEqual(panel._phase, "practice")
        self.assertIn("The review is weighing on you.", panel._transcript.text)
        self.assertIn(("user", "My review is tomorrow and I need rest"), client.intro_calls[0])

    def test_late_reply_cannot_overwrite_the_new_reply_or_its_source(self) -> None:
        client = ScriptedClient([QuestionTurn("unused")])
        panel = self._scripted_panel(client)
        workers = []
        received = []
        def launch(**kwargs):
            workers.append(kwargs["target"])
            return Mock()
        def response(state, value):
            client.status = state
            return value
        def receive(value):
            received.append((value, panel._response_status))
        with patch("app.ui.overlay.ai_panel.Thread", side_effect=launch):
            MeditationChatPanel._run_async(panel, response, LLMStatus("online"), "old", on_done=receive)
            workers.pop(0)()
            MeditationChatPanel._run_async(panel, response, LLMStatus("fallback", "timeout"), "new", on_done=receive)
            workers.pop(0)()
        for _delay, callback in panel._root.scheduled:
            callback()
        self.assertEqual(received, [("new", LLMStatus("fallback", "timeout"))])

    def test_closing_panel_cancels_a_queued_api_request(self) -> None:
        panel = self._scripted_panel(ScriptedClient([QuestionTurn("unused")]))
        workers = []
        function = Mock()
        def launch(**kwargs):
            workers.append(kwargs["target"])
            return Mock()
        with patch("app.ui.overlay.ai_panel.Thread", side_effect=launch):
            MeditationChatPanel._run_async(panel, function, on_done=Mock())
        panel._closed = True
        workers[0]()
        function.assert_not_called()


if __name__ == "__main__":
    unittest.main()
