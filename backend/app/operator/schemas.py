from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, Field


class OperatorMode(StrEnum):
    SLEEPING = "Sleeping"
    LISTENING = "Listening"
    THINKING = "Thinking"
    ACTING = "Acting"
    WAITING_FOR_APPROVAL = "Waiting for Approval"
    STOPPED = "Stopped"


class RiskLevel(StrEnum):
    SAFE = "safe"
    UNCERTAIN = "uncertain"
    APPROVAL_REQUIRED = "approval_required"
    BLOCKED = "blocked"


class OperatorCommand(BaseModel):
    text: str
    source: str = Field(default="text")
    language_hint: str = Field(default="auto")


class VoiceTranscriptionRequest(BaseModel):
    audio_base64: str
    mime_type: str = Field(default="audio/webm")
    language_hint: str = Field(default="auto")


class SpeakRequest(BaseModel):
    text: str


class OperatorApproval(BaseModel):
    action_id: int
    approved: bool


class DesktopActionRequest(BaseModel):
    action_type: str
    target: str | None = None
    text: str | None = None
    x: int | None = None
    y: int | None = None
    url: str | None = None
    command: str | None = None
    confidence: int = 100


class FolderSelection(BaseModel):
    folders: list[str]


class MemoryDeleteRequest(BaseModel):
    kind: str = Field(default="all")
    value: str | None = None


class OperatorPolicyRequest(BaseModel):
    reasoning_mode: str = Field(default="hybrid")


class FriendConsentRequest(BaseModel):
    friend_name: str
    consent_note: str
    consent_clip_path: str | None = None
    allowed_uses: list[str] = Field(default_factory=lambda: ["agent_replies", "voice_messages", "calls"])
    language: str = Field(default="English + Telugu")


class VoiceMessageRequest(BaseModel):
    recipient: str
    message: str
    use_friend_voice: bool = False


class MessageRequest(BaseModel):
    app: str = Field(default="WhatsApp")
    recipient: str
    message: str


class CallRequest(BaseModel):
    app: str
    contact_or_url: str
    use_friend_voice: bool = False
    record_call: bool = True


class PaymentRequest(BaseModel):
    app: str = Field(default="GPay")
    recipient: str
    amount: float
    note: str = Field(default="")
    upi_id: str | None = None


class OperatorStatus(BaseModel):
    mode: OperatorMode
    wake_phrase: str
    sleep_phrases: list[str]
    hotkey: str
    private_mode: bool
    vault_path: str
    desktop_entry: str
    current_session_id: int | None
    last_message: str


class OperatorHistoryItem(BaseModel):
    id: int
    session_id: int | None
    kind: str
    content: str
    risk_level: str
    status: str
    created_at: datetime
