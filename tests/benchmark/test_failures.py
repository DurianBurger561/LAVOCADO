"""Shared Benchmark Lab failure categories are derived from scalar rows."""

import unittest

from developer.benchmark.failures import FailureKind, failure_from_row


class FailureCaseTests(unittest.TestCase):
    def test_classifies_all_failure_categories(self) -> None:
        cases = (
            ({"outcome": "fp"}, FailureKind.FALSE_POSITIVE),
            ({"outcome": "fn"}, FailureKind.FALSE_NEGATIVE),
            (
                {"outcome": "incorrect", "target": "context_policy"},
                FailureKind.CONTEXT_CONFLICT,
            ),
            (
                {
                    "outcome": "fn",
                    "temporal_summary": {"confirmed": False},
                    "decision_summary": {"classification": "violation"},
                },
                FailureKind.TEMPORAL_MISS,
            ),
            ({"error": "capture_failed"}, FailureKind.CAPTURE_FAILURE),
            ({"error": "frame timeout"}, FailureKind.TIMEOUT),
        )
        for row, expected in cases:
            with self.subTest(kind=expected):
                failure = failure_from_row({"sample_id": "one", "config_id": "a", **row})
                self.assertIsNotNone(failure)
                self.assertIs(failure.kind, expected)
                self.assertEqual(failure.to_dict()["sample_id"], "one")

    def test_correct_row_is_not_a_failure(self) -> None:
        self.assertIsNone(failure_from_row({"outcome": "tp"}))


if __name__ == "__main__":
    unittest.main()
