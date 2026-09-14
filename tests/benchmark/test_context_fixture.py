"""Benchmark fixtures must resolve through product Context Policy."""

from __future__ import annotations

import unittest

from app.context.models import ContextPolicyAction
from developer.benchmark.context_fixture import context_policy_for_sample
from developer.benchmark.dataset import BenchmarkSample


class ContextFixtureTests(unittest.TestCase):
    def test_unknown_website_does_not_match_rule(self) -> None:
        sample = BenchmarkSample(
            "unknown", "unused.png", None, False,
            context_fixture={
                "application_identifier": "org.example.browser",
                "website_hostname": "blocked.example",
                "website_state": "unknown",
                "website_rules": [
                    {"domain": "blocked.example", "action": "force_block"}
                ],
            },
        )

        policy, context = context_policy_for_sample(sample)

        self.assertIs(policy.evaluate(context).action, ContextPolicyAction.NORMAL)

    def test_application_force_block_precedes_website_bypass(self) -> None:
        sample = BenchmarkSample(
            "priority", "unused.png", None, False,
            context_fixture={
                "application_identifier": "org.example.browser",
                "application_rules": [
                    {"identifier": "org.example.browser", "action": "force_block"}
                ],
                "website_hostname": "trusted.example",
                "website_rules": [
                    {"domain": "trusted.example", "action": "full_bypass"}
                ],
            },
        )

        policy, context = context_policy_for_sample(sample)

        self.assertIs(policy.evaluate(context).action, ContextPolicyAction.FORCE_BLOCK)

    def test_invalid_rule_is_rejected(self) -> None:
        sample = BenchmarkSample(
            "invalid", "unused.png", None, False,
            context_fixture={"application_rules": [{"action": "force_block"}]},
        )

        with self.assertRaises(ValueError):
            context_policy_for_sample(sample)
