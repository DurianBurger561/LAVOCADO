"""Rule persistence stores canonical identifiers and hostnames, not URLs."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.context.models import (
    ApplicationContext,
    ApplicationRule,
    ForegroundContext,
    WebsiteContext,
    WebsiteContextState,
    WebsiteMatchMode,
    WebsiteRule,
)
from app.context.models import (
    ContextPolicyAction as Action,
)
from app.context.policy.application import ApplicationPolicy
from app.context.policy.resolver import ContextPolicyService
from app.context.policy.website import WebsitePolicy
from app.context.settings import (
    RuleSettings,
    RuleSettingsStore,
    unmigrated_legacy_terms,
)
from app.intervention.recorder import EventRecorder, ProtectionEvent


class RuleSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "events.db"

    def test_round_trip_normalizes_keys_and_keeps_event_table(self) -> None:
        recorder = EventRecorder(self.database)
        recorder.record(ProtectionEvent("2026-01-01T00:00:00+00:00", "vision", "TEST", 0.8, 1))
        recorder.close()
        store = RuleSettingsStore(self.database)

        saved = store.save(RuleSettings(
            application_rules=(ApplicationRule(" Chrome.EXE ", Action.FORCE_BLOCK),),
            website_rules=(WebsiteRule(
                "https://WWW.Example.com/private?q=secret",
                Action.FULL_BYPASS,
                WebsiteMatchMode.DOMAIN_AND_SUBDOMAINS,
                False,
            ),),
        ))

        self.assertEqual(saved.application_rules[0].identifier, "chrome.exe")
        self.assertEqual(saved.website_rules[0].domain, "www.example.com")
        self.assertEqual(RuleSettingsStore(self.database).load(), saved)
        self.assertNotIn(b"private", self.database.read_bytes())
        self.assertNotIn(b"secret", self.database.read_bytes())
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM protection_events"
            ).fetchone()[0], 1)

    def test_conflicts_and_invalid_values_cannot_replace_existing_rules(self) -> None:
        store = RuleSettingsStore(self.database)
        original = store.save(RuleSettings(
            application_rules=(ApplicationRule("steam.exe", Action.FORCE_BLOCK),),
        ))
        conflicting = RuleSettings(application_rules=(
            ApplicationRule("STEAM.EXE", Action.FORCE_BLOCK),
            ApplicationRule("steam.exe", Action.FULL_BYPASS),
        ))
        with self.assertRaisesRegex(ValueError, "conflicting application"):
            store.save(conflicting)
        with self.assertRaisesRegex(ValueError, "conflicting website"):
            store.save(RuleSettings(website_rules=(
                WebsiteRule("example.com", Action.FORCE_BLOCK, WebsiteMatchMode.EXACT_HOST),
                WebsiteRule("https://example.com/private", Action.FULL_BYPASS,
                            WebsiteMatchMode.DOMAIN_AND_SUBDOMAINS),
            )))
        with self.assertRaises(ValueError):
            store.save(RuleSettings(application_rules=(
                ApplicationRule("https://private.example/path", Action.FORCE_BLOCK),
            )))
        with self.assertRaises(ValueError):
            store.save(RuleSettings(website_rules=(
                WebsiteRule("javascript:alert(1)", Action.FORCE_BLOCK,
                            WebsiteMatchMode.EXACT_HOST),
            )))
        self.assertEqual(store.load(), original)

    def test_legacy_migration_only_copies_stable_identifiers_once(self) -> None:
        terms = ("Chrome.EXE", "Steam", "reddit.com")
        store = RuleSettingsStore(self.database, legacy_blocked_apps=terms)

        self.assertEqual(
            store.load().application_rules,
            (ApplicationRule("chrome.exe", Action.FORCE_BLOCK),),
        )
        self.assertEqual(unmigrated_legacy_terms(terms), ("Steam", "reddit.com"))
        store.save(RuleSettings())
        self.assertEqual(
            RuleSettingsStore(self.database, legacy_blocked_apps=terms).load(),
            RuleSettings(),
        )

    def test_corrupt_conflicting_rows_still_resolve_force_block(self) -> None:
        store = RuleSettingsStore(self.database)
        with sqlite3.connect(self.database) as connection:
            connection.executemany(
                "INSERT INTO website_rules (domain, action, match_mode, enabled) "
                "VALUES (?, ?, ?, 1)",
                [
                    ("example.com", "full_bypass", "domain_and_subdomains"),
                    ("example.com", "force_block", "exact_host"),
                ],
            )
        settings = store.load()
        context = ForegroundContext(
            ApplicationContext("chrome.exe", "Chrome", "chrome.exe", "1", 0.0),
            True,
            WebsiteContext(WebsiteContextState.KNOWN, "chromium", "example.com", "test", 0.0),
            0.0,
        )
        policy = ContextPolicyService(
            ApplicationPolicy(settings.application_rules),
            WebsitePolicy(settings.website_rules),
        )

        self.assertEqual(policy.evaluate(context).action, Action.FORCE_BLOCK)


if __name__ == "__main__":
    unittest.main()
