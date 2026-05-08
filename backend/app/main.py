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
from .schemas import GitHubSettings, IncidentCreate


settings = get_settings()
db = Database(settings.db_path)
workflow = DevPilotWorkflow(db, settings)

app = FastAPI(title="DevPilot AI", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
