"""Privacy-safe request outcomes shared by the dashboard and overlay."""

from dataclasses import dataclass


# Never show a provider's raw error body: it may echo a key or user content.
_REASONS = {
    "no_key": ("No API key configured.", "未配置 API 密钥。"),
    "authentication": ("API authentication failed (401).", "API 认证失败（401），请检查密钥。"),
    "permission": ("API access denied (403).", "API 拒绝访问（403），请检查权限或地区限制。"),
    "not_found": ("Endpoint or model not found (404).", "接口地址或模型不存在（404）。"),
    "quota": ("API quota or balance exhausted.", "API 额度或余额不足。"),
    "rate_limit": ("API rate limit or quota reached (429).", "API 请求受限或额度不足（429）。"),
    "request": ("API rejected the request parameters.", "API 拒绝了请求参数，请检查模型和接口。"),
    "server": ("API service is temporarily unavailable.", "API 服务暂时不可用。"),
    "timeout": ("API request timed out.", "API 请求超时。"),
    "network": ("Could not reach the API. Check network and TLS settings.", "无法连接 API，请检查网络和 TLS 配置。"),
    "invalid_response": ("API returned an unusable response.", "API 已响应，但返回内容无法用于本轮练习。"),
    "unexpected": ("The AI request could not be completed.", "本轮 AI 请求未能完成。"),
}


@dataclass(frozen=True, slots=True)
class LLMStatus:
    state: str
    reason: str = ""

    def detail(self, language: str) -> str:
        if not self.reason:
            return ""
        messages = _REASONS.get(self.reason, _REASONS["unexpected"])
        return messages[1 if language == "zh" else 0]

    def public_view(self, language: str) -> dict[str, str]:
        return {"state": self.state, "reason": self.reason, "detail": self.detail(language)}
