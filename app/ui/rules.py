"""Small dashboard-facing editor for persisted context rules."""

from __future__ import annotations

from app.context.models import (
    ApplicationRule,
    ContextPolicyAction,
    WebsiteMatchMode,
    WebsiteRule,
)
from app.context.settings import (
    RuleSettings,
    RuleSettingsStore,
    normalize_application_identifier,
)
from app.context.website.normalization import normalize_hostname


class RuleConflict(ValueError):
    """An opposite-action rule exists for the same application or hostname."""


_GROUPS = {
    "blocked_applications": ("application", ContextPolicyAction.FORCE_BLOCK),
    "whitelisted_applications": ("application", ContextPolicyAction.FULL_BYPASS),
    "blocked_websites": ("website", ContextPolicyAction.FORCE_BLOCK),
    "whitelisted_websites": ("website", ContextPolicyAction.FULL_BYPASS),
}


class RuleEditor:
    def __init__(self, store: RuleSettingsStore) -> None:
        self.store = store

    def snapshot(self) -> dict[str, list[dict[str, object]]]:
        settings = self.store.load()
        result: dict[str, list[dict[str, object]]] = {key: [] for key in _GROUPS}
        for rule in settings.application_rules:
            group = (
                "blocked_applications" if rule.action is ContextPolicyAction.FORCE_BLOCK
                else "whitelisted_applications"
            )
            result[group].append({"identifier": rule.identifier, "enabled": rule.enabled})
        for rule in settings.website_rules:
            group = (
                "blocked_websites" if rule.action is ContextPolicyAction.FORCE_BLOCK
                else "whitelisted_websites"
            )
            result[group].append({
                "domain": rule.domain,
                "match_mode": rule.match_mode.value,
                "enabled": rule.enabled,
            })
        return result

    def add(
        self,
        group: str,
        value: str,
        match_mode: str = "exact_host",
        replace_conflict: bool = False,
    ) -> None:
        category, action = self._group(group)
        settings = self.store.load()
        if category == "application":
            identifier = normalize_application_identifier(value)
            existing = [
                rule for rule in settings.application_rules
                if rule.identifier == identifier
            ]
            if any(rule.action is not action for rule in existing) and not replace_conflict:
                raise RuleConflict("An opposite application rule exists. Replace it?")
            applications = tuple(
                rule for rule in settings.application_rules
                if rule.identifier != identifier
            ) + (ApplicationRule(identifier, action),)
            self.store.save(RuleSettings(applications, settings.website_rules))
            return

        domain = normalize_hostname(value)
        if domain is None:
            raise ValueError("Enter a valid website hostname or HTTPS URL.")
        mode = WebsiteMatchMode(match_mode)
        existing = [rule for rule in settings.website_rules if rule.domain == domain]
        if any(rule.action is not action for rule in existing) and not replace_conflict:
            raise RuleConflict("An opposite website rule exists. Replace it?")
        websites = tuple(
            rule for rule in settings.website_rules
            if not (
                rule.domain == domain
                and (rule.action is not action or rule.match_mode is mode)
            )
        ) + (WebsiteRule(domain, action, mode),)
        self.store.save(RuleSettings(settings.application_rules, websites))

    def remove(self, group: str, value: str, match_mode: str = "exact_host") -> bool:
        category, action = self._group(group)
        settings = self.store.load()
        if category == "application":
            identifier = normalize_application_identifier(value)
            applications = tuple(
                rule for rule in settings.application_rules
                if not (rule.identifier == identifier and rule.action is action)
            )
            changed = len(applications) != len(settings.application_rules)
            if changed:
                self.store.save(RuleSettings(applications, settings.website_rules))
            return changed

        domain = normalize_hostname(value)
        if domain is None:
            raise ValueError("Enter a valid website hostname.")
        mode = WebsiteMatchMode(match_mode)
        websites = tuple(
            rule for rule in settings.website_rules
            if not (rule.domain == domain and rule.action is action and rule.match_mode is mode)
        )
        changed = len(websites) != len(settings.website_rules)
        if changed:
            self.store.save(RuleSettings(settings.application_rules, websites))
        return changed

    @staticmethod
    def _group(group: str) -> tuple[str, ContextPolicyAction]:
        if not isinstance(group, str) or group not in _GROUPS:
            raise ValueError("Unknown rule group.")
        return _GROUPS[group]
