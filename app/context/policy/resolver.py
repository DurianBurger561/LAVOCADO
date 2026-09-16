"""Resolve independently evaluated application and website policies."""

from __future__ import annotations

from app.context.models import (
    ContextPolicyAction,
    ContextPolicyResult,
    ForegroundContext,
)
from app.context.policy.application import ApplicationPolicy
from app.context.policy.website import WebsitePolicy


def allows_vision(action: ContextPolicyAction | None) -> bool:
    """Run Vision only for NORMAL policy or when context is unavailable."""

    return action is None or action is ContextPolicyAction.NORMAL


def resolve_context_policy(
    app_action: ContextPolicyAction,
    website_action: ContextPolicyAction | None,
) -> ContextPolicyAction:
    actions = (app_action, website_action)
    if ContextPolicyAction.FORCE_BLOCK in actions:
        return ContextPolicyAction.FORCE_BLOCK
    if ContextPolicyAction.FULL_BYPASS in actions:
        return ContextPolicyAction.FULL_BYPASS
    return ContextPolicyAction.NORMAL


class ContextPolicyService:
    def __init__(
        self,
        application: ApplicationPolicy | None = None,
        website: WebsitePolicy | None = None,
    ) -> None:
        self.application = application or ApplicationPolicy()
        self.website = website or WebsitePolicy()

    def evaluate(self, context: ForegroundContext) -> ContextPolicyResult:
        """Evaluate application and website rules. Never inspects pixels."""
        app_rule = self.application.match(context.application)
        app_action = ContextPolicyAction.NORMAL if app_rule is None else app_rule.action

        if app_action is ContextPolicyAction.FORCE_BLOCK:
            return ContextPolicyResult(
                action=ContextPolicyAction.FORCE_BLOCK,
                app_action=app_action,
                website_action=ContextPolicyAction.NORMAL,
                matched_application_rule=app_rule,
            )

        website_rule = None
        website_action = ContextPolicyAction.NORMAL
        if context.is_browser and context.website is not None:
            website_rule = self.website.match(context.website)
            if website_rule is not None:
                website_action = website_rule.action

        return ContextPolicyResult(
            action=resolve_context_policy(app_action, website_action),
            app_action=app_action,
            website_action=website_action,
            matched_application_rule=app_rule,
            matched_website_rule=website_rule,
        )
