"""Language propagation from dashboard preferences to each intervention."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.intervention.sequence import default_intervention_sequence
from app.intervention.llm import LLMClient
from app.ui.language import save_ui_language
from app.ui.overlay.tk_backend import TkOverlayBackend
from app.ui.overlay.ai_panel import MeditationChatPanel


class OverlayLanguageTests(unittest.TestCase):
    def test_translated_stages_preserve_timing_and_dismissal(self):
        english = default_intervention_sequence("en")
        chinese = default_intervention_sequence("zh")
        for name in ("pause", "breathe", "ready"):
            en, zh = english.current, chinese.current
            self.assertEqual(en.name, name)
            self.assertEqual(zh.name, name)
            self.assertEqual(en.duration_seconds, zh.duration_seconds)
            self.assertEqual(en.can_dismiss, zh.can_dismiss)
            for field in ("title", "body", "button_label"):
                self.assertNotEqual(getattr(en, field), getattr(zh, field))
            english.advance()
            chinese.advance()

    def test_running_backend_reloads_language_on_each_show(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = TkOverlayBackend("Windows", data_dir=root)
            monitor = MagicMock(width=1920, height=1080, left=0, top=0)
            for language, title, exit_text in (
                ("zh", "先停下来一会儿", "退出"),
                ("en", "Pause for a moment", "Exit"),
            ):
                save_ui_language(root, language)
                tk = MagicMock()
                def check_step(*_args):
                    self.assertEqual(backend._sequence.current.title, title)
                    self.assertEqual(backend._language, language)
                with patch.dict("sys.modules", {"tkinter": tk}), patch(
                    "app.ui.overlay.tk_backend.FlatAction"
                ) as action, patch.object(backend, "_render_step", side_effect=check_step):
                    backend.show(monitor)
                    self.assertEqual(action.call_args.kwargs["text"], exit_text)
                    visible = [call.kwargs.get("text", "") for call in tk.Label.call_args_list]
                    self.assertIn(
                        "画面分析仅在本机进行。" if language == "zh"
                        else "Visual processing stays on this device.", visible
                    )

    def test_chat_interface_follows_ui_even_with_other_conversation_language(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for language, conversation, send in (("zh", "en", "发送"), ("en", "zh", "SEND")):
                save_ui_language(root, language)
                with patch.dict("sys.modules", {"tkinter": MagicMock()}), patch(
                    "app.ui.overlay.ai_panel.FlatAction"
                ):
                    panel = MeditationChatPanel(
                        MagicMock(), MagicMock(width=1920, height=1080),
                        on_exit=MagicMock(), data_dir=root,
                        client=LLMClient(language=conversation),
                    )
                self.assertEqual(panel._words["send"], send)
                self.assertEqual(panel._ui_language, language)
                self.assertEqual(panel._client.language, conversation)


if __name__ == "__main__":
    unittest.main()
