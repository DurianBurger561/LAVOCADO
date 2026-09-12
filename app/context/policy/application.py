"""Match stable foreground application identifiers, never window titles."""

from __future__ import annotations

from collections.abc import Iterable

from app.context.models import ApplicationContext, ApplicationRule, ContextPolicyAction


class ApplicationPolicy:
    def __init__(self, rules: Iterable[ApplicationRule] = ()) -> None:
        self.rules = tuple(rules)

    def match(self, context: ApplicationContext) -> ApplicationRule | None:
        if not context.identifier:
            return None
        identifier = context.identifier.casefold()
        bypass_rule = None
        for rule in self.rules:
            if not rule.enabled or rule.identifier.casefold() != identifier:
                continue
            if rule.action is ContextPolicyAction.FORCE_BLOCK:
                return rule
            if rule.action is ContextPolicyAction.FULL_BYPASS and bypass_rule is None:
                bypass_rule = rule
        return bypass_rule

    def evaluate(self, context: ApplicationContext) -> ContextPolicyAction:
        rule = self.match(context)
        return ContextPolicyAction.NORMAL if rule is None else rule.action

