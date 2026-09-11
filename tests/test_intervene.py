"""Tests for private, failure-tolerant intervention generation."""

import unittest
from dataclasses import dataclass

from app.intervention.intervene import (
    LOCAL_FALLBACK_MESSAGE,
    SAFE_EVENT_INPUT,
    SUPPORT_INSTRUCTIONS,
    InterventionGenerator,
)


@dataclass
class FakeResponse:
    output_text: str


class FakeResponses:
    def __init__(self, output_text: str = "Take a short walk away from the screen."):
        self.output_text = output_text
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> FakeResponse:
        self.calls.append(kwargs)
        return FakeResponse(self.output_text)


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


class FailingResponses:
    def create(self, **_kwargs: object) -> FakeResponse:
        raise ConnectionError("offline")


class InterventionGeneratorTests(unittest.TestCase):
    def test_uses_local_message_without_an_api_key(self) -> None:
        generator = InterventionGenerator(api_key="")
        self.addCleanup(generator.close)

        self.assertEqual(generator.generate(), LOCAL_FALLBACK_MESSAGE)

    def test_sends_only_fixed_non_sensitive_prompt_data(self) -> None:
        responses = FakeResponses("  Take a breath.   Close the page.  ")
        generator = InterventionGenerator(client=FakeClient(responses))
        self.addCleanup(generator.close)

        message = generator.generate_async().result(timeout=2)

        self.assertEqual(message, "Take a breath. Close the page.")
        self.assertEqual(len(responses.calls), 1)
        call = responses.calls[0]
        self.assertEqual(call["instructions"], SUPPORT_INSTRUCTIONS)
        self.assertEqual(call["input"], SAFE_EVENT_INPUT)
        self.assertEqual(call["reasoning"], {"effort": "none"})
        self.assertIs(call["store"], False)
        self.assertNotIn("image", call)
        self.assertNotIn("label", call)
        self.assertNotIn("confidence", call)
        self.assertNotIn("monitor_index", call)

    def test_falls_back_when_the_api_fails(self) -> None:
        generator = InterventionGenerator(
            client=FakeClient(FailingResponses()),
        )
        self.addCleanup(generator.close)

        with self.assertLogs("app.intervention.intervene", level="ERROR"):
            message = generator.generate()

        self.assertEqual(message, LOCAL_FALLBACK_MESSAGE)

    def test_falls_back_when_the_api_returns_empty_text(self) -> None:
        generator = InterventionGenerator(client=FakeClient(FakeResponses("  ")))
        self.addCleanup(generator.close)

        self.assertEqual(generator.generate(), LOCAL_FALLBACK_MESSAGE)


if __name__ == "__main__":
    unittest.main()
