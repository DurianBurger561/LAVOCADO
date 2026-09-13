"""Dashboard rule editing must remain explicit, local, and restart-safe."""

import tempfile
import unittest
from pathlib import Path

from app.context.settings import RuleSettingsStore
from app.ui.api import DashboardAPI
from app.ui.controller import ProtectionStatus


class Controller:
    def __init__(self) -> None:
        self.status = ProtectionStatus.STOPPED
        self.last_exit_code = None

    def start(self) -> bool:
        self.status = ProtectionStatus.RUNNING
        return True


class RuleEditorAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "events.db"
        self.controller = Controller()
        self.api = DashboardAPI(
            self.controller, object(), rule_store=RuleSettingsStore(self.database)
        )

    def test_application_conflict_requires_explicit_replacement(self) -> None:
        self.assertTrue(self.api.add_rule("blocked_applications", " Chrome.EXE ")["ok"])
        conflict = self.api.add_rule("whitelisted_applications", "chrome.exe")

        self.assertTrue(conflict["conflict"])
        self.assertEqual(
            self.api.get_rules()["rules"]["blocked_applications"],
            [{"identifier": "chrome.exe", "enabled": True}],
        )
        self.assertTrue(self.api.add_rule(
            "whitelisted_applications", "chrome.exe", replace_conflict=True
        )["ok"])
        self.assertEqual(self.api.get_rules()["rules"]["blocked_applications"], [])
        self.assertTrue(self.api.remove_rule("whitelisted_applications", "chrome.exe")["changed"])
        self.assertEqual(self.api.get_rules()["rules"]["whitelisted_applications"], [])

    def test_website_saves_only_hostname_and_replaces_all_opposite_modes(self) -> None:
        self.assertTrue(self.api.add_rule(
            "blocked_websites", "https://www.example.com/private?q=secret",
            "domain_and_subdomains",
        )["ok"])
        self.assertEqual(
            self.api.get_rules()["rules"]["blocked_websites"],
            [{"domain": "www.example.com", "match_mode": "domain_and_subdomains",
              "enabled": True}],
        )
        self.assertTrue(self.api.add_rule(
            "blocked_websites", "www.example.com", "exact_host"
        )["ok"])
        self.assertTrue(self.api.add_rule(
            "whitelisted_websites", "www.example.com", "exact_host"
        )["conflict"])
        self.assertTrue(self.api.add_rule(
            "whitelisted_websites", "www.example.com", "exact_host", True
        )["ok"])
        self.assertEqual(self.api.get_rules()["rules"]["blocked_websites"], [])
        self.assertNotIn(b"private", self.database.read_bytes())
        self.assertNotIn(b"secret", self.database.read_bytes())

    def test_running_protection_rejects_edits_and_preserves_rules(self) -> None:
        self.assertTrue(self.api.add_rule("blocked_applications", "steam.exe")["ok"])
        self.controller.status = ProtectionStatus.RUNNING

        self.assertFalse(self.api.get_rules()["can_edit"])
        self.assertFalse(self.api.add_rule("whitelisted_applications", "steam.exe")["ok"])
        self.assertFalse(self.api.remove_rule("blocked_applications", "steam.exe")["ok"])
        self.assertEqual(len(self.api.get_rules()["rules"]["blocked_applications"]), 1)

    def test_invalid_input_never_echoes_private_url(self) -> None:
        result = self.api.add_rule(
            "blocked_websites", "javascript:private-secret.example/path"
        )

        self.assertFalse(result["ok"])
        self.assertNotIn("private-secret", result["message"])
        self.assertFalse(self.api.add_rule("unknown", "chrome.exe")["ok"])


if __name__ == "__main__":
    unittest.main()
