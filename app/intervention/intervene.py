"""Generate a brief supportive message with a private local fallback."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Protocol

from app import config

LOGGER = logging.getLogger(__name__)

LOCAL_FALLBACK_MESSAGE = (
    "You are still in control. Close the triggering page, stand up, and take "
    "one small step toward what matters next."
)

SUPPORT_INSTRUCTIONS = (
    "Write one brief supportive message for a user of a self-chosen digital "
    "wellbeing tool. Be calm and non-judgmental. Do not diagnose the user, "
    "mention viewed content, or make medical claims. Offer one concrete next "
    "action. Return one or two sentences and no more than 35 words."
)

SAFE_EVENT_INPUT = (
    "The user's self-chosen protection feature was triggered. Provide the "
    "supportive intervention message."
)


class ResponseResult(Protocol):
    output_text: str


class ResponsesResource(Protocol):
    def create(self, **kwargs: object) -> ResponseResult: ...


class OpenAIClient(Protocol):
    responses: ResponsesResource


class InterventionGenerator:
    """Generate one message off the UI thread, falling back on any failure."""

    def __init__(
        self,
        client: OpenAIClient | None = None,
        *,
        api_key: str | None = None,
        model: str = config.INTERVENTION_MODEL,
        client_factory: Callable[..., OpenAIClient] | None = None,
    ) -> None:
        self._client = client
        self._api_key = os.environ.get("OPENAI_API_KEY") if api_key is None else api_key
        self._model = model
        self._client_factory = client_factory
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="lavocado-intervention",
        )
        self._close_lock = Lock()
        self._closed = False

    def generate(self) -> str:
        """Return an AI-generated message or the local fallback."""

        client = self._client
        if client is None and not self._api_key:
            return LOCAL_FALLBACK_MESSAGE

        try:
            if client is None:
                client = self._create_client()
            response = client.responses.create(
                model=self._model,
                instructions=SUPPORT_INSTRUCTIONS,
                input=SAFE_EVENT_INPUT,
                max_output_tokens=config.INTERVENTION_MAX_OUTPUT_TOKENS,
                reasoning={"effort": "none"},
                store=False,
            )
            message = self._normalize(response.output_text)
            return message or LOCAL_FALLBACK_MESSAGE
        except Exception:
            LOGGER.exception("AI intervention failed; using local fallback")
            return LOCAL_FALLBACK_MESSAGE

    def generate_async(self) -> Future[str]:
        """Queue message generation without delaying the protection overlay."""

        with self._close_lock:
            if self._closed:
                raise RuntimeError("InterventionGenerator is closed")
            return self._executor.submit(self.generate)

    def close(self) -> None:
        """Wait for any active request and release the worker."""

        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=True)

    def _create_client(self) -> OpenAIClient:
        factory = self._client_factory
        if factory is None:
            from openai import OpenAI

            factory = OpenAI

        return factory(
            api_key=self._api_key,
            timeout=config.INTERVENTION_API_TIMEOUT_SECONDS,
            max_retries=0,
        )

    @staticmethod
    def _normalize(message: str) -> str:
        compact = " ".join(message.split())
        if len(compact) <= 280:
            return compact
        return f"{compact[:277].rstrip()}..."
