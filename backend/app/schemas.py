from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, Field


class IncidentStatus(StrEnum):
    DETECTED = "Detected"
    ANALYZED = "Analyzed"
    FIX_ATTEMPTED = "Fix Attempted"
    FAILED = "Failed"
    SELF_CORRECTED = "Self-Corrected"
    RESOLVED = "Resolved"
    ESCALATED = "Escalated"


class Severity(StrEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class IncidentCreate(BaseModel):
    source_type: str = Field(default="manual")
    title: str = Field(default="New incident")
    logs: str = Field(default="")
    repo_path: str | None = None
    test_command: str = Field(default="python -m pytest")
    sample_key: str | None = None


class GitHubSettings(BaseModel):
    owner: str | None = None
    repo: str | None = None
    base_branch: str = "main"
    token: str | None = None


class Incident(BaseModel):
    id: int
    title: str
    source_type: str
    status: IncidentStatus
    severity: Severity
    confidence: int
    root_cause: str
    time_saved_minutes: int
    repo_path: str | None
    workspace_path: str | None
    test_command: str
    logs: str
    created_at: datetime
    updated_at: datetime


class AgentEvent(BaseModel):
    id: int
    incident_id: int
    agent_name: str
    step_type: str
    message: str
    status: str
    created_at: datetime


class RepairAttempt(BaseModel):
    id: int
    incident_id: int
    attempt_number: int
    patch_summary: str
    test_command: str
    test_result: str
    logs: str
    created_at: datetime


class MistakeResolution(BaseModel):
    id: int
    incident_id: int
    agent_name: str
    mistake: str
    cause: str
    attempted_action: str
    result: str
    final_resolution: str
    prevention_note: str
    status: str
    created_at: datetime


class SecurityReview(BaseModel):
    id: int
    incident_id: int
    risk_level: str
    risky_files: list[str]
    blocked_reason: str
    approval_required: bool
    created_at: datetime


class RollbackPlan(BaseModel):
    id: int
    incident_id: int
    affected_files: list[str]
    revert_steps: list[str]
    rollback_command: str
    risk_notes: str
    created_at: datetime


class KnowledgeBaseEntry(BaseModel):
    id: int
    error_signature: str
    root_cause: str
    fix_summary: str
    outcome: str
    reuse_count: int
    created_at: datetime


class PullRequestDraft(BaseModel):
    id: int
    incident_id: int
    title: str
    body: str
    branch: str
    commit_hash: str
    diff_summary: str
    status: str
    pr_url: str | None
    created_at: datetime


class IncidentDetail(BaseModel):
    incident: Incident
    events: list[AgentEvent]
    attempts: list[RepairAttempt]
    mistakes: list[MistakeResolution]
    security_reviews: list[SecurityReview]
    rollback_plan: RollbackPlan | None
    memory: list[KnowledgeBaseEntry]
    pr_draft: PullRequestDraft | None
    diff: str
    voice_briefing: str
