"""Build edition flag stays user unless Developer entry sets it."""

from __future__ import annotations

import unittest

from app import build_edition


class BuildEditionTests(unittest.TestCase):
    def tearDown(self) -> None:
        build_edition.set_build_edition(build_edition.USER_EDITION)

    def test_default_is_user(self) -> None:
        build_edition.set_build_edition(build_edition.USER_EDITION)
        self.assertEqual(build_edition.BUILD_EDITION, "user")
        self.assertFalse(build_edition.is_developer_edition())
        self.assertEqual(build_edition.app_display_name(), "LAVOCADO")

    def test_developer_entry_can_switch_edition(self) -> None:
        build_edition.set_build_edition(build_edition.DEVELOPER_EDITION)
        self.assertTrue(build_edition.is_developer_edition())
        self.assertEqual(build_edition.app_display_name(), "LAVOCADO Developer")

    def test_unknown_edition_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_edition.set_build_edition("hidden-lab")
