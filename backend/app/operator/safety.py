from __future__ import annotations

from .schemas import DesktopActionRequest, RiskLevel


SENSITIVE_TERMS = (
    "delete",
    "remove",
    "send",
    "message",
    "pay",
    "payment",
    "password",
    "token",
    "credential",
    "install",
    "settings",
    "commit",
    "push",
    "pull request",
    "approve pr",
    "call",
    "voice message",
)

BLOCKED_TERMS = (
    "steal",
    "hide recording",
    "without telling",
    "bypass password",
    "exfiltrate",
)


def classify_text(text: str) -> tuple[RiskLevel, str]:
    lowered = text.lower()
    if any(term in lowered for term in BLOCKED_TERMS):
        return RiskLevel.BLOCKED, "Request asks for hidden, credential, or unsafe behavior."
    if any(term in lowered for term in SENSITIVE_TERMS):
        return RiskLevel.APPROVAL_REQUIRED, "Sensitive action requires voice and popup approval."
    return RiskLevel.SAFE, "No sensitive action detected."


def classify_desktop_action(action: DesktopActionRequest) -> tuple[RiskLevel, str]:
    joined = " ".join(
        str(part)
        for part in [action.action_type, action.target, action.text, action.url, action.command]
        if part
    )
    if action.confidence < 75:
        return RiskLevel.UNCERTAIN, "Target confidence is low; approval is required before clicking or typing."
    return classify_text(joined)
