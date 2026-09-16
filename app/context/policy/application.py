"""Match foreground applications without relying on mutable window titles."""

from __future__ import annotations

from collections.abc import Iterable

from app.context.models import ApplicationContext, ApplicationRule, ContextPolicyAction


class ApplicationPolicy:
    def __init__(self, rules: Iterable[ApplicationRule] = ()) -> None:
        self.rules = tuple(rules)

    def match(self, context: ApplicationContext) -> ApplicationRule | None:
        candidates = _application_match_candidates(context)
        if not candidates:
            return None
        bypass_rule = None
        for rule in self.rules:
            if not rule.enabled or rule.identifier.casefold() not in candidates:
                continue
            if rule.action is ContextPolicyAction.FORCE_BLOCK:
                return rule
            if rule.action is ContextPolicyAction.FULL_BYPASS and bypass_rule is None:
                bypass_rule = rule
        return bypass_rule

    def evaluate(self, context: ApplicationContext) -> ContextPolicyAction:
        rule = self.match(context)
        return ContextPolicyAction.NORMAL if rule is None else rule.action


def _application_match_candidates(context: ApplicationContext) -> frozenset[str]:
    """Accept stable IDs and the native app name, but never window titles.

    macOS exposes a bundle ID such as ``com.apple.Safari`` while users often
    enter the visible application name (``Safari``). Windows similarly exposes
    both an executable name and its stem. Supporting both forms keeps manual
    entries useful without falling back to mutable window-title matching.
    """

    return frozenset(
        value.casefold()
        for value in (context.identifier, context.display_name)
        if isinstance(value, str) and value.strip()
    )
