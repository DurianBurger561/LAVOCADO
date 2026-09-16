"""Tests for the optional, privacy-limited meditation LLM support."""

import json
import io
import os
import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

from app.intervention.llm import (
    OFFLINE_QUESTIONS,
    LLMClient,
    MeditationContext,
    fallback_questions,
    practice_name,
    resolve_language,
    time_of_day,
    today_trigger_count,
)

PRACTICE_NAME = practice_name("zh")


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class LLMTests(unittest.TestCase):
    def test_time_of_day_uses_coarse_buckets(self) -> None:
        self.assertEqual(time_of_day(2), "late_night")
        self.assertEqual(time_of_day(8), "morning")
        self.assertEqual(time_of_day(14), "afternoon")
        self.assertEqual(time_of_day(20), "evening")

    def test_no_key_uses_local_fallbacks(self) -> None:
        client = LLMClient()
        context = MeditationContext(2, "late_night")

        turn = client.generate_question(context, [])
        self.assertIn(turn.question, fallback_questions(context))
        self.assertTrue(turn.reflection)
        self.assertFalse(turn.enough)
        line = client.generate_practice_line(
            context,
            [("user", "压力很大，睡不着")],
            [],
            0,
        )
        self.assertIn("吸气", line)

    def test_offline_reflection_answers_what_the_user_just_said(self) -> None:
        client = LLMClient()
        context = MeditationContext(1, "evening")

        opening = client.generate_question(context, [])
        bored = client.generate_question(
            context, [("assistant", opening.question), ("user", "就是有点无聊")]
        )
        tired = client.generate_question(
            context, [("assistant", opening.question), ("user", "今天太累了")]
        )

        self.assertIn("无聊", bored.reflection)
        self.assertIn("累", tired.reflection)
        self.assertNotEqual(bored.reflection, opening.reflection)

    def test_offline_questions_do_not_repeat_and_stop_at_the_cap(self) -> None:
        client = LLMClient()
        context = MeditationContext(1, "evening")
        conversation: list[tuple[str, str]] = []

        asked: list[str] = []
        for _index in range(OFFLINE_QUESTIONS):
            turn = client.generate_question(context, conversation)
            asked.append(turn.question)
            conversation.append(("assistant", turn.question))
            conversation.append(("user", "有点累"))

        self.assertEqual(len(set(asked)), OFFLINE_QUESTIONS)
        turn = client.generate_question(context, conversation)
        self.assertTrue(turn.enough)
        self.assertEqual(turn.question, "")

    def test_the_model_cannot_end_the_check_in_on_the_first_turn(self) -> None:
        def opener(_request: object, timeout: float) -> FakeResponse:
            del timeout
            return FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "reflection": "听起来今天不太好过。",
                                        "question": "现在身体是什么感觉？",
                                        "enough": True,
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                }
            )

        client = LLMClient(api_key="test-key", opener=opener)
        context = MeditationContext(1, "evening")
        conversation: list[tuple[str, str]] = []

        first = client.generate_question(context, conversation)
        self.assertFalse(first.enough)
        self.assertEqual(client.status.reason, "invalid_response")
        conversation.extend([("assistant", first.question), ("user", "今天和同事争吵，很委屈，想安静一下")])
        ready = client.generate_question(context, conversation)
        self.assertTrue(ready.enough)
        self.assertEqual(ready.question, "")
        self.assertEqual(ready.reflection, "听起来今天不太好过。")
        self.assertEqual(client.status.state, "online")

    def test_offline_intro_names_the_typing_meditation(self) -> None:
        intro = LLMClient().generate_practice_intro(
            MeditationContext(3, "late_night"),
            [("assistant", "现在身体是什么感觉？"), ("user", "有点累，睡不着")],
        )

        self.assertIn(PRACTICE_NAME, intro.invitation)
        self.assertIn("累", intro.invitation)
        self.assertTrue(intro.first_line)

    def test_intro_adds_the_practice_name_when_the_model_omits_it(self) -> None:
        def opener(_request: object, timeout: float) -> FakeResponse:
            del timeout
            return FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "invitation": "听起来你现在有点紧。我们慢一分钟。",
                                        "first_line": "我慢慢吸气，再慢慢呼气。",
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                }
            )

        intro = LLMClient(api_key="test-key", opener=opener).generate_practice_intro(
            MeditationContext(1, "evening"), [("user", "有点紧")]
        )

        self.assertIn(PRACTICE_NAME, intro.invitation)
        self.assertIn("听起来你现在有点紧", intro.invitation)
        self.assertEqual(intro.first_line, "我慢慢吸气，再慢慢呼气。")

    def test_question_turn_reads_json_and_bare_replies(self) -> None:
        replies = [
            '```json\n{"reflection": "谢谢你说这些。", "question": "现在最想要的是什么？",'
            ' "enough": true}\n```',
            "现在最想要的是什么？",
        ]

        def opener(_request: object, timeout: float) -> FakeResponse:
            del timeout
            return FakeResponse(
                {"choices": [{"message": {"content": replies.pop(0)}}]}
            )

        client = LLMClient(api_key="test-key", opener=opener)
        context = MeditationContext(1, "morning")
        started = [
            ("assistant", "第一问"), ("user", "答一"),
            ("assistant", "第二问"), ("user", "答二"),
        ]

        fenced = client.generate_question(context, started)
        self.assertEqual(fenced.question, "")
        self.assertEqual(fenced.reflection, "谢谢你说这些。")
        self.assertTrue(fenced.enough)

        bare = client.generate_question(context, [])
        self.assertEqual(bare.question, "现在最想要的是什么？")
        self.assertEqual(bare.reflection, "")
        self.assertFalse(bare.enough)

    def test_question_prompt_carries_the_earlier_answers(self) -> None:
        captured: list[dict[str, object]] = []

        def opener(request: object, timeout: float) -> FakeResponse:
            del timeout
            captured.append(json.loads(request.data.decode("utf-8")))  # type: ignore[attr-defined]
            return FakeResponse(
                {"choices": [{"message": {"content": "还有别的吗？"}}]}
            )

        LLMClient(api_key="test-key", opener=opener).generate_question(
            MeditationContext(2, "late_night"),
            [("assistant", "现在身体什么感觉？"), ("user", "很烦，睡不着")],
        )

        serialized = json.dumps(captured[0], ensure_ascii=False)
        self.assertIn("很烦，睡不着", serialized)
        self.assertIn("已经聊了 1 轮", serialized)
        self.assertIn(PRACTICE_NAME, serialized)

    def test_every_stage_receives_product_role_and_knowledge_boundaries(self) -> None:
        requirements = {
            "zh": ("戒色应用", "核心任务是劝导用户停止浏览色情内容", "关闭色情页面",
                   "不要替继续浏览找理由", "误报或手动测试", "不是心理医生",
                   "没有收到本次具体触发原因", "触发次数不是", "五轮", "随时退出"),
            "en": ("pornography-cessation app", "actively encourage the user to stop viewing pornography",
                   "close the pornography page", "Do not justify continued viewing",
                   "blocking rules", "false positive or a manual test",
                   "not a psychologist or licensed therapist", "specific trigger reason",
                   "Trigger count is not", "five personalized", "exit at any time"),
        }
        for language, phrases in requirements.items():
            with self.subTest(language=language):
                captured = []
                responses = [
                    json.dumps({"reflection": "Hello", "question": "How are you?", "enough": False}),
                    json.dumps({"invitation": "Let's try typing meditation", "first_line": "I can pause."}),
                    "I can choose my next step.",
                    "Thank you for taking a pause.",
                ]

                def opener(request, timeout):
                    captured.append(json.loads(request.data))
                    return FakeResponse({"choices": [{"message": {"content": responses.pop(0)}}]})

                client = LLMClient(api_key="fake", opener=opener, language=language)
                context = MeditationContext(2, "evening")
                conversation = [("user", "I want to pause this habit.")]
                client.generate_question(context, conversation)
                client.generate_practice_intro(context, conversation)
                client.generate_practice_line(context, conversation, [], 1)
                client.generate_closing(context, conversation, [])

                self.assertEqual(len(captured), 4)
                for request in captured:
                    system, user = request["messages"]
                    self.assertEqual(system["role"], "system")
                    self.assertIn("LAVOCADO", system["content"])
                    for phrase in phrases:
                        self.assertIn(phrase, system["content"])
                    self.assertEqual(user["role"], "user")
                    self.assertIn(conversation[0][1], user["content"])

    def test_checkin_prompt_addresses_identity_trigger_and_recovery_questions(self) -> None:
        requirements = {
            "zh": ("你是谁", "为什么激活你", "我能恢复吗", "再看五分钟", "question 可以为空",
                   "此前回答若遗漏背景", "不默认身体损伤", "不要求立即解释",
                   "不代表已经足够了解练习需要", "只学回应方式，不照抄成固定台词"),
            "en": ("Who are you?", "why this app activated you?", "Can I recover?", "five more minutes",
                   "question may be empty", "an earlier answer missed this context",
                   "without presuming bodily damage", "without demanding an explanation",
                   "do not establish practice readiness", "do not repeat scripted lines"),
        }
        for language, phrases in requirements.items():
            with self.subTest(language=language):
                prompt = LLMClient(language=language).pack.checkin_system
                for phrase in phrases:
                    self.assertIn(phrase, prompt)

    def test_direct_answer_without_a_question_remains_online(self) -> None:
        captured = []
        reflection = "我是 LAVOCADO 的 AI 陪伴者，帮助你在冲动或情绪中停一下。"

        def opener(request, timeout):
            captured.append(json.loads(request.data))
            return FakeResponse({"choices": [{"message": {"content": json.dumps({
                "reflection": reflection, "question": "", "enough": False,
            })}}]})

        conversation = [
            ("assistant", "你能告诉我一下，这个程序对你来说意味着什么吗？"),
            ("user", "难道你不知道 LAVOCADO 让你来做什么？"),
        ]
        client = LLMClient(api_key="fake", opener=opener)
        turn = client.generate_question(MeditationContext(1, "evening"), conversation)

        self.assertEqual(turn.reflection, reflection)
        self.assertEqual(turn.question, "")
        self.assertFalse(turn.enough)
        self.assertEqual(client.status.state, "online")
        for _, utterance in conversation:
            self.assertIn(utterance, captured[0]["messages"][1]["content"])

    def test_empty_or_malformed_direct_answers_still_use_local_fallback(self) -> None:
        for reply in (
            {"reflection": "", "question": "", "enough": False},
            {"reflection": " ", "question": " ", "enough": False},
            {"reflection": "A reply", "question": None, "enough": False},
            {"reflection": "A reply", "question": [], "enough": False},
            {"reflection": "A reply", "question": "", "enough": "false"},
        ):
            with self.subTest(reply=reply):
                def opener(request, timeout):
                    return FakeResponse({"choices": [{"message": {"content": json.dumps(reply)}}]})

                client = LLMClient(api_key="fake", opener=opener)
                turn = client.generate_question(MeditationContext(1, "evening"), [("user", "Who are you?")])
                self.assertEqual(client.status.reason, "invalid_response")
                self.assertTrue(turn.question)
                self.assertFalse(turn.enough)

    def test_english_client_talks_and_guides_in_english(self) -> None:
        captured: list[dict[str, object]] = []

        def opener(request: object, timeout: float) -> FakeResponse:
            del timeout
            captured.append(json.loads(request.data.decode("utf-8")))  # type: ignore[attr-defined]
            return FakeResponse({"choices": [{"message": {"content": "{}"}}]})

        client = LLMClient(api_key="test-key", opener=opener, language="en")
        context = MeditationContext(2, "late_night")
        conversation = [("assistant", "How are you?"), ("user", "worn out")]

        turn = client.generate_question(context, conversation)
        intro = client.generate_practice_intro(context, conversation)
        closing = client.fallback_closing()

        serialized = json.dumps(captured, ensure_ascii=False)
        self.assertIn("typing meditation", serialized)
        self.assertNotIn("打字冥想", serialized)
        self.assertIn("This is trigger 2 today", serialized)
        self.assertIn("typing meditation", intro.invitation)
        self.assertIn("worn out", intro.invitation)
        self.assertIn("typing meditation", closing)
        for text in (turn.question, turn.reflection, intro.first_line):
            self.assertFalse(any("一" <= character <= "鿿" for character in text))

    def test_offline_english_pack_covers_the_whole_practice(self) -> None:
        client = LLMClient(language="en")
        context = MeditationContext(1, "late_night")
        conversation = [("assistant", "How are you?"), ("user", "just bored")]

        turn = client.generate_question(context, conversation)
        intro = client.generate_practice_intro(context, conversation)
        line = client.generate_practice_line(context, conversation, [], 2)

        self.assertIn("bored", turn.reflection)
        self.assertIn(practice_name("en"), intro.invitation)
        self.assertIn("bored", intro.invitation)
        self.assertIn("five minutes", line)

    def test_language_falls_back_to_the_dashboard_choice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            (data_dir / "ui-language.json").write_text(
                json.dumps({"language": "en"}), encoding="utf-8"
            )
            with patch.dict("os.environ", {}, clear=False):
                os.environ.pop("LAVOCADO_LLM_LANGUAGE", None)
                self.assertEqual(resolve_language("", data_dir), "en")
                self.assertEqual(resolve_language("zh", data_dir), "zh")
                os.environ["LAVOCADO_LLM_LANGUAGE"] = "zh"
                self.assertEqual(resolve_language("", data_dir), "zh")

    def test_saved_language_reaches_the_overlay_client(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            (data_dir / "llm_settings.json").write_text(
                json.dumps({"api_key": "k", "language": "en", "enabled": True}),
                encoding="utf-8",
            )

            client = LLMClient.from_environment(data_dir)

            self.assertEqual(client.language, "en")
            self.assertEqual(client.pack.practice_name, "typing meditation")

    def test_saved_settings_override_environment_for_overlay_client(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            (data_dir / "llm_settings.json").write_text(
                json.dumps(
                    {
                        "api_key": "saved-key",
                        "endpoint": "https://example.test/v1",
                        "model": "saved-model",
                        "enabled": True,
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {
                    "LAVOCADO_LLM_API_KEY": "environment-key",
                    "LAVOCADO_LLM_ENDPOINT": "https://environment.test/v1",
                    "LAVOCADO_LLM_MODEL": "environment-model",
                },
                clear=False,
            ):
                client = LLMClient.from_environment(data_dir)

            self.assertEqual(client.api_key, "saved-key")
            self.assertEqual(client.endpoint, "https://example.test/v1/chat/completions")
            self.assertEqual(client.model, "saved-model")

    def test_today_trigger_count_reads_only_event_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            with sqlite3.connect(data_dir / "events.db") as connection:
                connection.execute(
                    "CREATE TABLE protection_events (occurred_at TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO protection_events VALUES (?)",
                    (datetime.now(timezone.utc).isoformat(),),
                )
                connection.execute(
                    "INSERT INTO protection_events VALUES ('2000-01-01T00:00:00+00:00')"
                )

            self.assertEqual(today_trigger_count(data_dir), 1)

    def test_remote_payload_contains_only_allowed_context(self) -> None:
        captured: list[dict[str, object]] = []

        def opener(request: object, timeout: float) -> FakeResponse:
            del timeout
            data = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
            captured.append(data)
            return FakeResponse(
                {"choices": [{"message": {"content": "先慢慢吸气，再呼气。"}}]}
            )

        client = LLMClient(
            api_key="test-key",
            endpoint="https://example.test/v1",
            model="test-model",
            opener=opener,
        )
        client.generate_practice_line(
            MeditationContext(4, "late_night"),
            [("assistant", "你现在感觉怎样？"), ("user", "压力很大")],
            [("assistant", "慢慢呼吸"), ("user", "慢慢呼吸")],
            1,
        )

        self.assertEqual(len(captured), 1)
        serialized = json.dumps(captured[0], ensure_ascii=False)
        self.assertIn("压力很大", serialized)
        self.assertIn("late_night", serialized)
        self.assertIn("今天第 4 次", serialized)
        for forbidden in ("pornhub", "chrome.exe", "window title", "monitor 2"):
            self.assertNotIn(forbidden, serialized)

    def test_online_checkin_has_no_forced_turn_limit_and_keeps_early_context(self) -> None:
        captured = []

        def opener(request, timeout):
            captured.append(json.loads(request.data))
            return FakeResponse({"choices": [{"message": {"content": json.dumps({
                "reflection": "Let's stay with what you just said.",
                "question": "Which part feels hardest?", "enough": False,
            })}}]})

        conversation = [("user", "My project review is tomorrow")]
        for i in range(12):
            conversation.extend([("assistant", f"Question {i}"), ("user", f"Answer {i}")])
        client = LLMClient(api_key="fake", opener=opener, language="en")
        turn = client.generate_question(MeditationContext(1, "evening"), conversation)
        self.assertFalse(turn.enough)
        self.assertIn("My project review is tomorrow", json.dumps(captured))
        self.assertIn("Answer 11", json.dumps(captured))

    def test_configuration_is_not_connection_success(self) -> None:
        client = LLMClient(api_key="not-a-real-key")
        self.assertTrue(client.configured)
        self.assertEqual(client.status.state, "unverified")

    def test_request_failures_are_distinct_and_never_expose_provider_secrets(self) -> None:
        errors = [
            (urllib.error.HTTPError("https://test", 401, "secret-key", {}, None), "authentication"),
            (urllib.error.HTTPError("https://test", 403, "raw-user-text", {}, None), "permission"),
            (urllib.error.HTTPError("https://test", 404, "model", {}, None), "not_found"),
            (urllib.error.HTTPError("https://test", 429, "limit", {}, io.BytesIO(b'{"error":{"code":"insufficient_quota","message":"secret-key"}}')), "quota"),
            (urllib.error.HTTPError("https://test", 429, "limit", {}, io.BytesIO(b'{}')), "rate_limit"),
            (urllib.error.HTTPError("https://test", 503, "bad", {}, None), "server"),
            (TimeoutError("secret-key"), "timeout"),
            (urllib.error.URLError(TimeoutError()), "timeout"),
            (urllib.error.URLError("raw-user-text"), "network"),
        ]
        for error, reason in errors:
            with self.subTest(reason=reason):
                def opener(_request, timeout):
                    raise error
                client = LLMClient(api_key="secret-key", opener=opener)
                turn = client.generate_question(MeditationContext(1, "morning"), [])
                self.assertTrue(turn.question)
                self.assertEqual(client.status.state, "fallback")
                self.assertEqual(client.status.reason, reason)
                public = json.dumps(client.status.public_view("en"))
                self.assertNotIn("secret-key", public)
                self.assertNotIn("raw-user-text", public)

    def test_invalid_outputs_are_marked_local_for_every_generation_stage(self) -> None:
        def opener(_request, timeout):
            return FakeResponse({"choices": [{"message": {"content": "{}"}}]})

        client = LLMClient(api_key="fake", opener=opener)
        context = MeditationContext(1, "morning")
        for call in (
            lambda: client.generate_question(context, []),
            lambda: client.generate_practice_intro(context, []),
            lambda: client.generate_practice_line(context, [], [], 0),
            lambda: client.generate_closing(context, [], []),
        ):
            call()
            self.assertEqual(client.status.state, "fallback")
            self.assertEqual(client.status.reason, "invalid_response")

    def test_status_recovers_after_a_failed_turn(self) -> None:
        responses = [TimeoutError(), "Which deadline worries you?"]
        def opener(_request, timeout):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return FakeResponse({"choices": [{"message": {"content": response}}]})
        client = LLMClient(api_key="fake", opener=opener)
        context = MeditationContext(1, "morning")
        client.generate_question(context, [])
        self.assertEqual(client.status.state, "fallback")
        client.generate_question(context, [("user", "There is a deadline")])
        self.assertEqual(client.status.state, "online")
        self.assertEqual(client.status.reason, "")


if __name__ == "__main__":
    unittest.main()
