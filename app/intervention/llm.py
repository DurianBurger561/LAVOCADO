"""Optional, privacy-limited LLM support for the intervention overlay.

The client speaks the OpenAI-compatible chat-completions protocol using only
the standard library. Without a configured key, every method returns a local
fallback so the overlay remains useful offline.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_BULLET_PREFIX = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


class LLMUnavailable(RuntimeError):
    """The optional remote model cannot be used for this turn."""


@dataclass(frozen=True, slots=True)
class MeditationContext:
    today_trigger_count: int
    time_of_day: str


def time_of_day(hour: int | None = None) -> str:
    """Return a coarse local time bucket, never a timestamp."""

    current_hour = datetime.now().hour if hour is None else int(hour)
    if current_hour < 5 or current_hour >= 22:
        return "late_night"
    if current_hour < 12:
        return "morning"
    if current_hour < 18:
        return "afternoon"
    return "evening"


def today_trigger_count(data_dir: Path | None = None) -> int:
    """Read only today's event count; return one for the current intervention."""

    if data_dir is None:
        return 1
    database = data_dir / "events.db"
    if not database.is_file():
        return 1
    start = (
        datetime.now()
        .astimezone()
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(timezone.utc)
        .isoformat()
    )
    try:
        with sqlite3.connect(database, timeout=0.2) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM protection_events WHERE occurred_at >= ?",
                (start,),
            ).fetchone()
        return max(1, int(row[0] if row else 0))
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return 1


class LLMClient:
    """Small OpenAI-compatible client with no persistent conversation state."""

    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        *,
        opener: Callable[..., Any] | None = None,
        timeout: float = 8.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.endpoint = _normalize_endpoint(endpoint)
        self.model = model.strip() or DEFAULT_MODEL
        self._opener = opener or urllib.request.urlopen
        self.timeout = timeout

    @classmethod
    def from_environment(cls) -> "LLMClient":
        return cls(
            api_key=(
                os.environ.get("LAVOCADO_LLM_API_KEY")
                or os.environ.get("OPENAI_API_KEY")
                or os.environ.get("DEEPSEEK_API_KEY")
            ),
            endpoint=(
                os.environ.get("LAVOCADO_LLM_ENDPOINT")
                or os.environ.get("OPENAI_BASE_URL")
                or os.environ.get("DEEPSEEK_BASE_URL")
                or DEFAULT_ENDPOINT
            ),
            model=(
                os.environ.get("LAVOCADO_LLM_MODEL")
                or os.environ.get("OPENAI_MODEL")
                or os.environ.get("DEEPSEEK_MODEL")
                or DEFAULT_MODEL
            ),
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> str:
        if not self.configured:
            raise LLMUnavailable("no API key configured")
        payload = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
        except Exception as error:  # noqa: BLE001 - remote errors must fail closed
            raise LLMUnavailable("LLM request failed") from error
        if not isinstance(content, str) or not content.strip():
            raise LLMUnavailable("LLM returned no text")
        return content.strip()

    def generate_questions(self, context: MeditationContext) -> list[str]:
        fallback = fallback_questions(context)
        try:
            raw = self.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是一个温和的陪伴者，帮助正在对抗强迫性冲动的人平复下来。"
                            "请生成 3 个简短、开放、不评判的问题，了解用户此刻的状态。"
                            "问题从情绪、身体状态、今天发生的事、此刻真正想要的角度切入，"
                            "不要询问或猜测用户看了什么，不说教，不制造羞耻。"
                            "每个问题单独一行，只返回问题列表。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"今天第 {context.today_trigger_count} 次，时间段 {context.time_of_day}。"
                        ),
                    },
                ],
                temperature=0.9,
                max_tokens=240,
            )
            questions = _parse_lines(raw, limit=5)
            return questions or fallback
        except LLMUnavailable:
            return fallback

    def generate_practice_line(
        self,
        context: MeditationContext,
        conversation: list[tuple[str, str]],
        history: list[tuple[str, str]],
        round_index: int,
    ) -> str:
        fallbacks = fallback_practice_lines(context, conversation)
        fallback = fallbacks[min(round_index, len(fallbacks) - 1)]
        try:
            raw = self.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是一个温和的正念和冲动冲浪引导者。"
                            "帮助用户做 60 到 90 秒的打字冥想。"
                            "一次只返回一句让用户打字复述的简短引导语，"
                            "结合缓慢呼吸、觉察冲动、接纳它像波浪一样退去。"
                            "深夜或疲惫时偏向休息，无聊时给一个五分钟内可执行的小动作，"
                            "用户说忍不住时使用冲动冲浪。不要评判、说教或猜测用户看了什么。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": _practice_context_text(
                            context,
                            conversation,
                            history,
                            round_index,
                        ),
                    },
                ],
                temperature=0.8,
                max_tokens=180,
            )
            return _parse_line(raw) or fallback
        except LLMUnavailable:
            return fallback

    def generate_closing(
        self,
        context: MeditationContext,
        conversation: list[tuple[str, str]],
        history: list[tuple[str, str]],
    ) -> str:
        fallback = (
            "你已经为自己留出了一分钟。现在感受一下身体，接下来做一件温和的小事。"
        )
        try:
            raw = self.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是温和、不评判的正念陪伴者。请用一句简短的话收尾，"
                            "肯定用户刚才完成的练习，邀请 TA 感受现在的状态，"
                            "并提醒随时可以停下。只返回一句话。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": _practice_context_text(
                            context,
                            conversation,
                            history,
                            len(history),
                        ),
                    },
                ],
                temperature=0.7,
                max_tokens=120,
            )
            return _parse_line(raw) or fallback
        except LLMUnavailable:
            return fallback


def fallback_questions(_context: MeditationContext) -> list[str]:
    return [
        "此刻你的身体更接近紧绷、疲惫，还是只是想找点刺激？",
        "如果不批评自己，你觉得刚才真正想得到的是什么？",
        "接下来五分钟，什么小动作会让你更靠近自己想要的状态？",
    ]


def fallback_practice_lines(
    context: MeditationContext,
    conversation: list[tuple[str, str]],
) -> list[str]:
    spoken = " ".join(text for _role, text in conversation).casefold()
    if any(word in spoken for word in ("无聊", "bored", "没事", "nothing")):
        return [
            "先吸气四下，再慢慢呼气六下。",
            "我现在只是无聊，不是真的需要这个。",
            "这个念头会过去，我可以去做一件五分钟的小事。",
            "我先站起来喝一杯水，再决定下一步。",
            "我正在把注意力温和地带回自己的生活。",
        ]
    if context.time_of_day == "late_night" or any(
        word in spoken for word in ("压力", "睡不着", "累", "stress", "sleep")
    ):
        return [
            "吸气数四下，停一下，再用六下呼气。",
            "今天已经很累了，我不用再逼自己。",
            "我现在真正需要的是休息，不是继续消耗自己。",
            "这个冲动可以在我休息时自己慢慢退下去。",
            "我允许今晚简单一点，先把身体带回安静。",
        ]
    return [
        "慢慢吸气四下，再慢慢呼气六下。",
        "我注意到这个冲动，但我不需要立刻跟着它行动。",
        "这个感觉像一阵浪，它现在很高，也会退下去。",
        "我只需要等这一阵过去，不必和它争斗。",
        "我可以把手和注意力带回眼前这一件小事。",
    ]


def _normalize_endpoint(value: str) -> str:
    endpoint = (value or DEFAULT_ENDPOINT).strip().rstrip("/")
    if endpoint.endswith("/chat/completions"):
        return endpoint
    if endpoint.endswith("/v1"):
        return endpoint + "/chat/completions"
    return endpoint + "/v1/chat/completions"


def _parse_lines(raw: str, *, limit: int) -> list[str]:
    lines = []
    for value in raw.splitlines():
        cleaned = _BULLET_PREFIX.sub("", value).strip().strip('"“”')
        if cleaned:
            lines.append(cleaned[:240])
        if len(lines) >= limit:
            break
    return lines


def _parse_line(raw: str) -> str:
    lines = _parse_lines(raw, limit=1)
    return lines[0] if lines else ""


def _practice_context_text(
    context: MeditationContext,
    conversation: list[tuple[str, str]],
    history: list[tuple[str, str]],
    round_index: int,
) -> str:
    conversation_text = "\n".join(
        f"{role}: {text[:500]}" for role, text in conversation[-10:]
    ) or "用户还没有补充说明。"
    history_text = "\n".join(
        f"{role}: {text[:500]}" for role, text in history[-10:]
    ) or "还没有开始复述。"
    return (
        f"今天第 {context.today_trigger_count} 次，时间段 {context.time_of_day}。\n"
        f"用户主动说过：\n{conversation_text}\n"
        f"本次练习第 {round_index + 1} 轮，已有对话：\n{history_text}"
    )
