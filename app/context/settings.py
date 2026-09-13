"""Validated, privacy-limited application and website rule storage."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from app.context.browser_registry import DEFAULT_BROWSERS
from app.context.models import (
    ApplicationRule,
    ContextPolicyAction,
    WebsiteMatchMode,
    WebsiteRule,
)
from app.context.website.normalization import normalize_hostname

_KNOWN_IDENTIFIERS = frozenset(
    definition.application_identifier.casefold() for definition in DEFAULT_BROWSERS
)
_RULE_ACTIONS = frozenset(
    {ContextPolicyAction.FORCE_BLOCK, ContextPolicyAction.FULL_BYPASS}
)


@dataclass(frozen=True, slots=True)
class RuleSettings:
    application_rules: tuple[ApplicationRule, ...] = ()
    website_rules: tuple[WebsiteRule, ...] = ()


def normalize_application_identifier(value: str) -> str:
    """Accept one stable executable/bundle identifier, never a path or title URL."""

    if not isinstance(value, str):
        raise TypeError("application identifier must be text")
    identifier = value.strip().casefold()
    if (
        not identifier
        or len(identifier) > 255
        or not any(char.isalnum() for char in identifier)
        or any(ord(char) < 32 or ord(char) == 127 for char in identifier)
        or any(char in identifier for char in "/\\:?#")
    ):
        raise ValueError("invalid application identifier")
    return identifier


def normalize_rule_settings(settings: RuleSettings) -> RuleSettings:
    """Canonicalize rule keys and reject silent block/whitelist conflicts."""

    applications: dict[str, ApplicationRule] = {}
    websites: dict[tuple[str, WebsiteMatchMode], WebsiteRule] = {}
    website_actions: dict[str, ContextPolicyAction] = {}
    for rule in settings.application_rules:
        identifier = normalize_application_identifier(rule.identifier)
        _validate_rule_fields(rule.action, rule.enabled)
        previous = applications.get(identifier)
        if previous is not None and previous.action is not rule.action:
            raise ValueError("conflicting application rules")
        applications[identifier] = ApplicationRule(identifier, rule.action, rule.enabled)

    for rule in settings.website_rules:
        domain = normalize_hostname(rule.domain)
        if domain is None:
            raise ValueError("invalid website domain")
        _validate_rule_fields(rule.action, rule.enabled)
        if not isinstance(rule.match_mode, WebsiteMatchMode):
            raise TypeError("invalid website match mode")
        previous_action = website_actions.get(domain)
        if previous_action is not None and previous_action is not rule.action:
            raise ValueError("conflicting website rules")
        website_actions[domain] = rule.action
        websites[(domain, rule.match_mode)] = WebsiteRule(
            domain, rule.action, rule.match_mode, rule.enabled
        )
    return RuleSettings(tuple(applications.values()), tuple(websites.values()))


def unmigrated_legacy_terms(terms: Iterable[str]) -> tuple[str, ...]:
    """Keep ambiguous old title substrings in the legacy watcher unchanged."""

    return tuple(term for term in terms if _legacy_identifier(term) is None)


class RuleSettingsStore:
    """Store only rule definitions in the existing local SQLite data file."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        legacy_blocked_apps: Iterable[str] = (),
    ) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._legacy_terms = tuple(legacy_blocked_apps)
        self._initialize_database()

    def load(self) -> RuleSettings:
        """Read all valid persisted rules; resolver handles damaged conflicts."""

        with closing(self._connect()) as connection:
            app_rows = connection.execute(
                "SELECT identifier, action, enabled FROM application_rules ORDER BY identifier"
            ).fetchall()
            site_rows = connection.execute(
                "SELECT domain, action, match_mode, enabled FROM website_rules "
                "ORDER BY domain, match_mode"
            ).fetchall()

        applications = []
        for row in app_rows:
            try:
                action = ContextPolicyAction(row["action"])
                if action not in _RULE_ACTIONS or row["enabled"] not in (0, 1):
                    continue
                applications.append(ApplicationRule(
                    normalize_application_identifier(row["identifier"]),
                    action,
                    bool(row["enabled"]),
                ))
            except (TypeError, ValueError):
                continue
        websites = []
        for row in site_rows:
            try:
                domain = normalize_hostname(row["domain"])
                action = ContextPolicyAction(row["action"])
                if (
                    domain is None
                    or action not in _RULE_ACTIONS
                    or row["enabled"] not in (0, 1)
                ):
                    continue
                websites.append(WebsiteRule(
                    domain,
                    action,
                    WebsiteMatchMode(row["match_mode"]),
                    bool(row["enabled"]),
                ))
            except (TypeError, ValueError):
                continue
        return RuleSettings(tuple(applications), tuple(websites))

    def save(self, settings: RuleSettings) -> RuleSettings:
        """Atomically replace rule tables after strict validation."""

        normalized = normalize_rule_settings(settings)
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM application_rules")
            connection.execute("DELETE FROM website_rules")
            connection.executemany(
                "INSERT INTO application_rules (identifier, action, enabled) "
                "VALUES (?, ?, ?)",
                [
                    (rule.identifier, rule.action.value, int(rule.enabled))
                    for rule in normalized.application_rules
                ],
            )
            connection.executemany(
                "INSERT INTO website_rules (domain, action, match_mode, enabled) "
                "VALUES (?, ?, ?, ?)",
                [
                    (rule.domain, rule.action.value, rule.match_mode.value,
                     int(rule.enabled))
                    for rule in normalized.website_rules
                ],
            )
        return normalized

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=2.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_database(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS application_rules (
                    identifier TEXT PRIMARY KEY COLLATE NOCASE,
                    action TEXT NOT NULL CHECK (action IN ('force_block', 'full_bypass')),
                    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1))
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS website_rules (
                    domain TEXT NOT NULL COLLATE NOCASE,
                    action TEXT NOT NULL CHECK (action IN ('force_block', 'full_bypass')),
                    match_mode TEXT NOT NULL
                        CHECK (match_mode IN ('exact_host', 'domain_and_subdomains')),
                    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                    PRIMARY KEY (domain, match_mode)
                )
                """
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS context_rule_migrations (name TEXT PRIMARY KEY)"
            )
            self._migrate_legacy(connection)

    def _migrate_legacy(self, connection: sqlite3.Connection) -> None:
        if not self._legacy_terms:
            return
        digest = hashlib.sha256(
            "\0".join(self._legacy_terms).encode("utf-8")
        ).hexdigest()
        marker = f"blocked_apps_v1:{digest}"
        if connection.execute(
            "SELECT 1 FROM context_rule_migrations WHERE name = ?", (marker,)
        ).fetchone() is not None:
            return
        for term in self._legacy_terms:
            identifier = _legacy_identifier(term)
            if identifier is not None:
                connection.execute(
                    "INSERT INTO application_rules (identifier, action, enabled) "
                    "VALUES (?, 'force_block', 1) "
                    "ON CONFLICT(identifier) DO UPDATE SET action='force_block', enabled=1",
                    (identifier,),
                )
        connection.execute(
            "INSERT INTO context_rule_migrations (name) VALUES (?)", (marker,)
        )


def _legacy_identifier(term: str) -> str | None:
    try:
        identifier = normalize_application_identifier(term)
    except (TypeError, ValueError):
        return None
    if identifier.endswith(".exe") or identifier in _KNOWN_IDENTIFIERS:
        return identifier
    return None


def _validate_rule_fields(action: ContextPolicyAction, enabled: bool) -> None:
    if action not in _RULE_ACTIONS or not isinstance(action, ContextPolicyAction):
        raise ValueError("invalid rule action")
    if not isinstance(enabled, bool):
        raise TypeError("enabled must be boolean")
