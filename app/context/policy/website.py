"""Match known hostnames against exact-host or domain-boundary rules."""

from __future__ import annotations

from collections.abc import Iterable

from app.context.models import (
    ContextPolicyAction,
    WebsiteContext,
    WebsiteContextState,
    WebsiteMatchMode,
    WebsiteRule,
)
from app.context.website.normalization import normalize_hostname


class WebsitePolicy:
    def __init__(self, rules: Iterable[WebsiteRule] = ()) -> None:
        self.rules = tuple(rules)

    def match(self, context: WebsiteContext) -> WebsiteRule | None:
        if context.state is not WebsiteContextState.KNOWN or not context.hostname:
            return None
        host = normalize_hostname(context.hostname)
        if host is None:
            return None
        bypass_rule = None
        for rule in self.rules:
            if not rule.enabled:
                continue
            domain = normalize_hostname(rule.domain)
            if domain is None:
                continue
            matches = host == domain or (
                rule.match_mode is WebsiteMatchMode.DOMAIN_AND_SUBDOMAINS
                and host.endswith("." + domain)
            )
            if not matches:
                continue
            if rule.action is ContextPolicyAction.FORCE_BLOCK:
                return rule
            if rule.action is ContextPolicyAction.FULL_BYPASS and bypass_rule is None:
                bypass_rule = rule
        return bypass_rule

    def evaluate(self, context: WebsiteContext) -> ContextPolicyAction:
        rule = self.match(context)
        return ContextPolicyAction.NORMAL if rule is None else rule.action
