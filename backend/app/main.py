from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .agents.workflow import DevPilotWorkflow
from .config import get_settings
from .core.github_client import create_pull_request
from .database import Database
from .operator.schemas import (
    CallRequest,
    DesktopActionRequest,
    FolderSelection,
    FriendConsentRequest,
    MessageRequest,
    MemoryDeleteRequest,
    OperatorApproval,
    OperatorCommand,
    OperatorPolicyRequest,
    PaymentRequest,
    SpeakRequest,
    VoiceTranscriptionRequest,
    VoiceMessageRequest,
)
from .operator.service import OperatorService
from .operator.vault import PrivateVault
from .operator.voice_runtime import LocalSpeaker, VoiceRuntime
from .schemas import GitHubSettings, IncidentCreate


settings = get_settings()
db = Database(settings.db_path)
workflow = DevPilotWorkflow(db, settings)
operator = OperatorService(db, PrivateVault(), settings)
speaker = LocalSpeaker()
voice_runtime: VoiceRuntime | None = None

app = FastAPI(title="DevPilot AI", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def start_desktop_listener() -> None:
    global voice_runtime
    if not settings.desktop_voice_enabled:
        return
    if voice_runtime is None:
        voice_runtime = VoiceRuntime(operator, run_operator_text, speaker)
    voice_runtime.start()


@app.get("/")
def root() -> dict:
    return {
        "name": "DevPilot AI Backend",
        "status": "running",
        "message": "This is the API server. Open the dashboard at http://127.0.0.1:5173.",
        "links": {
            "dashboard": "http://127.0.0.1:5173",
            "health": "http://127.0.0.1:8000/api/health",
            "api_docs": "http://127.0.0.1:8000/docs",
        },
    }


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "reasoning_model": settings.openai_reasoning_model,
        "coding_model": settings.openai_coding_model,
        "remote_ai_configured": bool(settings.openai_api_key),
        "desktop_voice_enabled": settings.desktop_voice_enabled,
        "chinna": operator.status(),
    }


@app.post("/api/incidents")
def create_incident(payload: IncidentCreate) -> dict:
    source = payload.repo_path
    title = payload.title
    logs = payload.logs
    if payload.source_type == "sample" or payload.sample_key:
        source = str(settings.sample_repo_path)
        title = "Sample repo failing tests"
        logs = logs or "Sample suite contains a broken import, wrong API response contract, and missing validation."
    incident = db.create_incident(
        {
            "title": title,
            "source_type": payload.source_type,
            "logs": logs,
            "repo_path": source,
            "test_command": payload.test_command,
        }
    )
    db.add_event(incident["id"], "Perception Layer", "Detected", "Incident created from intake source.", "complete")
    return detail(incident["id"])


@app.get("/api/incidents")
def list_incidents() -> list[dict]:
    return db.list_incidents()


@app.get("/api/incidents/{incident_id}")
def detail(incident_id: int) -> dict:
    try:
        return db.incident_detail(incident_id, workflow.get_diff(incident_id), workflow.voice_briefing(incident_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/incidents/{incident_id}/run")
async def run_incident(incident_id: int, background: bool = Query(default=False)) -> dict:
    try:
        db.get_incident(incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if background:
        asyncio.create_task(workflow.run(incident_id))
        return {"started": True, "incident_id": incident_id}
    return await workflow.run(incident_id)


@app.get("/api/incidents/{incident_id}/events")
async def stream_events(incident_id: int):
    async def event_generator():
        last_count = -1
        for _ in range(60):
            current = db.incident_detail(incident_id)["events"]
            if len(current) != last_count:
                yield f"data: {json.dumps(current)}\n\n"
                last_count = len(current)
            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/incidents/{incident_id}/diff")
def diff(incident_id: int) -> dict:
    return {"diff": workflow.get_diff(incident_id)}


@app.get("/api/incidents/{incident_id}/mistakes")
def mistakes(incident_id: int) -> list[dict]:
    return db.incident_detail(incident_id)["mistakes"]


@app.get("/api/incidents/{incident_id}/rollback")
def rollback(incident_id: int) -> dict | None:
    return db.incident_detail(incident_id)["rollback_plan"]


@app.get("/api/incidents/{incident_id}/voice-briefing")
def voice_briefing(incident_id: int) -> dict:
    return {"briefing": workflow.voice_briefing(incident_id)}


@app.post("/api/incidents/{incident_id}/approve-pr")
async def approve_pr(incident_id: int) -> dict:
    details = db.incident_detail(incident_id, workflow.get_diff(incident_id), workflow.voice_briefing(incident_id))
    draft = details["pr_draft"]
    if not draft:
        raise HTTPException(status_code=409, detail="No PR draft is ready yet.")

    configured = db.get_setting("github", {})
    token = configured.get("token") or settings.github_token
    owner = configured.get("owner") or settings.github_owner
    repo = configured.get("repo") or settings.github_repo
    base = configured.get("base_branch") or settings.github_base_branch

    if token and owner and repo:
        try:
            url = await create_pull_request(token, owner, repo, draft["title"], draft["body"], draft["branch"], base)
            db.upsert_pr_draft(
                incident_id,
                draft["title"],
                draft["body"],
                draft["branch"],
                draft["commit_hash"],
                draft["diff_summary"],
                "created",
                url,
            )
            db.add_event(incident_id, "GitHub Action Layer", "PR Created", f"Created GitHub PR: {url}", "complete")
            return {"status": "created", "pr_url": url}
        except Exception as exc:
            db.add_event(incident_id, "GitHub Action Layer", "PR Preview", f"GitHub PR creation failed safely: {exc}", "failed")

    db.upsert_pr_draft(
        incident_id,
        draft["title"],
        draft["body"],
        draft["branch"],
        draft["commit_hash"],
        draft["diff_summary"],
        "preview-ready",
        None,
    )
    return {"status": "preview-ready", "message": "GitHub credentials or remote branch are unavailable; PR draft preview is ready."}


@app.get("/api/memory/search")
def search_memory(q: str = "") -> list[dict]:
    return db.search_memory(q or "incident")


@app.post("/api/settings/github")
def save_github_settings(payload: GitHubSettings) -> dict:
    db.set_setting(
        "github",
        {
            "owner": payload.owner,
            "repo": payload.repo,
            "base_branch": payload.base_branch,
            "token": payload.token,
            "token_present": bool(payload.token),
        },
    )
    return {"saved": True, "token_present": bool(payload.token)}


@app.get("/api/sample/status")
def sample_status() -> dict:
    return {"sample_repo_exists": Path(settings.sample_repo_path).exists(), "path": str(settings.sample_repo_path)}


@app.get("/api/operator/status")
def operator_status() -> dict:
    return operator.status()


@app.get("/api/operator/policy")
def operator_policy() -> dict:
    return operator.operator_policy()


@app.post("/api/operator/policy")
def save_operator_policy(payload: OperatorPolicyRequest) -> dict:
    return operator.save_operator_policy(payload)


@app.post("/api/operator/session/wake")
def operator_wake() -> dict:
    return operator.wake("api")


@app.post("/api/operator/session/sleep")
def operator_sleep() -> dict:
    return operator.sleep()


@app.post("/api/operator/session/stop")
def operator_stop() -> dict:
    return operator.stop()


@app.post("/api/operator/command")
async def operator_command(payload: OperatorCommand) -> dict:
    return await run_operator_text(payload.text)


async def run_operator_text(text: str) -> dict:
    async def run_devpilot_demo():
        created = create_incident(
            IncidentCreate(
                source_type="sample",
                sample_key="sample-suite",
                test_command="python -m pytest",
            )
        )
        incident_id = created["incident"]["id"]
        return await workflow.run(incident_id)

    return await operator.command(text, run_devpilot_demo)


@app.post("/api/operator/voice/transcribe")
def operator_voice_transcribe(payload: VoiceTranscriptionRequest) -> dict:
    return operator.transcribe_voice(payload)


@app.post("/api/operator/speak")
def operator_speak(payload: SpeakRequest) -> dict:
    speaker.speak(payload.text)
    return {"ok": True, "speaking": True}


@app.post("/api/operator/voice-listener/start")
def operator_voice_listener_start() -> dict:
    global voice_runtime
    if voice_runtime is None:
        voice_runtime = VoiceRuntime(operator, run_operator_text, speaker)
    return voice_runtime.start().__dict__


@app.post("/api/operator/voice-listener/stop")
def operator_voice_listener_stop() -> dict:
    if voice_runtime is None:
        return {"enabled": False, "listening": False, "speaking": speaker.speaking, "last_transcript": "", "last_reply": "", "last_error": "", "processed_chunks": 0, "wake_phrase": "Hey Chinna WakeUp", "mode": operator.status()["mode"]}
    return voice_runtime.stop().__dict__


@app.get("/api/operator/voice-listener/status")
def operator_voice_listener_status() -> dict:
    if voice_runtime is None:
        return {"enabled": False, "listening": False, "speaking": speaker.speaking, "last_transcript": "", "last_reply": "", "last_error": speaker.last_error, "processed_chunks": 0, "wake_phrase": "Hey Chinna WakeUp", "mode": operator.status()["mode"]}
    return voice_runtime.status().__dict__


@app.get("/api/operator/history")
def operator_history(limit: int = 100) -> list[dict]:
    return operator.history(limit)


@app.get("/api/operator/approvals")
def operator_approvals() -> list[dict]:
    return operator.pending_approvals()


@app.post("/api/operator/action/approve")
def operator_approve(payload: OperatorApproval) -> dict:
    return operator.approve(payload.action_id, payload.approved)


@app.get("/api/operator/observation")
def operator_observation() -> dict:
    return operator.observe()


@app.post("/api/operator/desktop/action")
def operator_desktop_action(payload: DesktopActionRequest) -> dict:
    return operator.desktop_action(payload)


@app.get("/api/privacy/vault/status")
def privacy_vault_status() -> dict:
    return operator.vault_status()


@app.get("/api/privacy/memory/search")
def privacy_memory_search(q: str = "") -> list[dict]:
    return operator.memory_search(q)


@app.delete("/api/privacy/memory")
def privacy_memory_delete(payload: MemoryDeleteRequest) -> dict:
    return operator.memory_delete(payload)


@app.post("/api/privacy/export")
def privacy_export() -> dict:
    return operator.privacy_export()


@app.get("/api/privacy/folders")
def privacy_folders() -> list[dict]:
    return operator.indexed_folders()


@app.post("/api/privacy/folders")
def privacy_save_folders(payload: FolderSelection) -> list[dict]:
    return operator.save_indexed_folders(payload.folders)


@app.post("/api/friend-voice/consent")
def friend_voice_consent(payload: FriendConsentRequest) -> dict:
    return operator.save_friend_consent(payload)


@app.post("/api/voice-message")
def voice_message(payload: VoiceMessageRequest) -> dict:
    return operator.voice_message(payload)


@app.post("/api/messages/prepare")
def prepare_message(payload: MessageRequest) -> dict:
    return operator.prepare_message(payload)


@app.post("/api/calls/start")
def start_call(payload: CallRequest) -> dict:
    return operator.start_call(payload)


@app.post("/api/payments/prepare")
def prepare_payment(payload: PaymentRequest) -> dict:
    return operator.prepare_payment(payload)
