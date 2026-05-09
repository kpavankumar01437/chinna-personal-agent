from __future__ import annotations

import json
import os
import base64
import binascii
import importlib.util
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ..agents.llm import OpenAIModelRouter
from ..config import Settings
from ..database import Database, utcnow
from .desktop import DesktopControlService
from .safety import classify_desktop_action, classify_text
from .schemas import (
    CallRequest,
    DesktopActionRequest,
    FriendConsentRequest,
    MessageRequest,
    MemoryDeleteRequest,
    OperatorPolicyRequest,
    OperatorMode,
    PaymentRequest,
    RiskLevel,
    VoiceTranscriptionRequest,
    VoiceMessageRequest,
)
from .vault import PrivateVault


WAKE_PHRASE = "hey chinna wakeup"
SLEEP_PHRASES = ("sleep", "go to sleep")
HOTKEY = "Alt+Space"
_WHISPER_MODEL: Any | None = None
DEFAULT_OPERATOR_POLICY = {
    "supervision_mode": "supervised",
    "reasoning_mode": "hybrid",
    "internet_mode": "browser-only-while-awake",
    "reviewed_folder_access_only": True,
    "messages_require_approval": True,
    "calls_require_approval": True,
    "payments_require_approval": True,
    "friend_voice_enabled": True,
    "friend_voice_fallback": "generic-local-tts",
}
APPROVAL_SCOPES = [
    "messages",
    "payments",
    "calls",
    "custom-voice",
    "deletes",
    "installs",
    "system-settings",
    "credentials",
]
BLOCKED_INDEX_NAMES = {
    ".aws",
    ".azure",
    ".codex",
    ".git",
    ".gradle",
    ".npm",
    ".nuget",
    ".ssh",
    ".vscode",
    "__pycache__",
    "appdata",
    "application data",
    "cache",
    "cookies",
    "local settings",
    "packages",
    "program files",
    "program files (x86)",
    "programdata",
    "temp",
    "tmp",
    "windows",
}


class OperatorService:
    def __init__(self, db: Database, vault: PrivateVault, settings: Settings | None = None):
        self.db = db
        self.vault = vault
        self.settings = settings or Settings(_env_file=None)
        self.router = OpenAIModelRouter(self.settings)
        self.desktop = DesktopControlService(vault)
        self._init_db()
        self.vault.ensure()

    def _init_db(self) -> None:
        with self.db.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS operator_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mode TEXT NOT NULL,
                    wake_phrase TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    last_message TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS operator_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS operator_approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    action_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS indexed_folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS friend_voice_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    friend_name TEXT NOT NULL,
                    consent_note TEXT NOT NULL,
                    consent_clip_path TEXT,
                    allowed_uses TEXT NOT NULL,
                    language TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS call_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app TEXT NOT NULL,
                    contact_or_url TEXT NOT NULL,
                    disclosure TEXT NOT NULL,
                    recording_policy TEXT NOT NULL,
                    status TEXT NOT NULL,
                    vault_record_path TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            row = conn.execute("SELECT id FROM operator_sessions ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO operator_sessions (mode, wake_phrase, started_at, last_message) VALUES (?, ?, ?, ?)",
                    (OperatorMode.SLEEPING.value, "Hey Chinna WakeUp", utcnow(), "Sleeping. Wake listener only."),
                )

    def status(self) -> dict[str, Any]:
        session = self._current_session()
        vault_info = self.vault.ensure()
        policy = self.operator_policy()
        return {
            "mode": session["mode"],
            "wake_phrase": "Hey Chinna WakeUp",
            "sleep_phrases": list(SLEEP_PHRASES),
            "hotkey": HOTKEY,
            "private_mode": True,
            "vault_path": vault_info["vault_path"],
            "desktop_entry": vault_info["desktop_entry"],
            "current_session_id": session["id"],
            "last_message": session["last_message"],
            "local_ai": self.local_ai_status(),
            "policy": policy,
            "friend_voice": self.friend_voice_status(),
        }

    def operator_policy(self) -> dict[str, Any]:
        stored = self.db.get_setting("operator_policy", {})
        policy = {**DEFAULT_OPERATOR_POLICY, **(stored if isinstance(stored, dict) else {})}
        policy["supervision_mode"] = "supervised"
        policy["reasoning_mode"] = policy["reasoning_mode"] if policy["reasoning_mode"] in {"local-only", "hybrid"} else "hybrid"
        policy["reviewed_folder_access_only"] = True
        policy["messages_require_approval"] = True
        policy["calls_require_approval"] = True
        policy["payments_require_approval"] = True
        policy["friend_voice_fallback"] = "generic-local-tts"
        policy["cloud_available"] = bool(self.settings.openai_api_key)
        policy["cloud_enabled"] = bool(self.settings.openai_api_key) and policy["reasoning_mode"] == "hybrid"
        policy["approval_required_for"] = APPROVAL_SCOPES
        policy["indexing_notes"] = "Reviewed user folders only. System folders, browser profiles, AppData, and SSH/credential paths stay blocked."
        return policy

    def save_operator_policy(self, payload: OperatorPolicyRequest) -> dict[str, Any]:
        reasoning_mode = payload.reasoning_mode.strip().lower()
        if reasoning_mode not in {"local-only", "hybrid"}:
            reasoning_mode = DEFAULT_OPERATOR_POLICY["reasoning_mode"]
        self.db.set_setting("operator_policy", {"reasoning_mode": reasoning_mode})
        self._history(
            self._current_session()["id"],
            "policy",
            f"Operator reasoning mode set to {reasoning_mode}.",
            RiskLevel.SAFE,
            "complete",
        )
        return self.operator_policy()

    def wake(self, source: str = "manual") -> dict[str, Any]:
        session = self._set_mode(OperatorMode.LISTENING, f"Awake via {source}. Listening for natural commands.")
        self._history(session["id"], "session", "Chinna woke up. Screen observation is now available.", RiskLevel.SAFE, "complete")
        return self.status()

    def sleep(self) -> dict[str, Any]:
        session = self._set_mode(OperatorMode.SLEEPING, "Sleeping. Wake listener only; no screen observation.")
        self._history(session["id"], "session", "Chinna went to sleep. Observation and actions stopped.", RiskLevel.SAFE, "complete")
        return self.status()

    def stop(self) -> dict[str, Any]:
        session = self._set_mode(OperatorMode.STOPPED, "Emergency stop activated. Pending actions halted.")
        self._history(session["id"], "stop", "Emergency stop activated.", RiskLevel.APPROVAL_REQUIRED, "stopped")
        return self.status()

    async def command(self, text: str, run_devpilot_callback=None) -> dict[str, Any]:
        cleaned = text.strip()
        lowered = cleaned.lower()
        session = self._current_session()

        if _has_wake_phrase(cleaned):
            self.wake("wake phrase")
            cleaned = _remove_wake_phrase(cleaned)
            if not cleaned:
                reply = "I am awake and listening."
                self.vault.store_json(
                    "transcript",
                    f"session-{session['id']}-{_stamp()}",
                    {"user": text.strip(), "reply": reply, "plan": {"intent": "wake", "steps": ["Wake session", "Start listening"]}},
                )
                return {"status": self.status(), "reply": reply, "plan": ["Wake session", "Start listening"], "risk": RiskLevel.SAFE.value}
            lowered = cleaned.lower()
            session = self._current_session()

        if any(phrase == lowered for phrase in SLEEP_PHRASES):
            return {"status": self.sleep(), "reply": "Going to sleep now.", "plan": []}

        if session["mode"] == OperatorMode.SLEEPING.value:
            return {
                "status": self.status(),
                "reply": "I am sleeping. Say Hey Chinna WakeUp or press Alt+Space to activate me.",
                "plan": [],
            }

        risk, reason = classify_text(cleaned)
        self._history(session["id"], "user-command", cleaned, risk, "received")
        if risk == RiskLevel.BLOCKED:
            self._history(session["id"], "blocked", reason, risk, "blocked")
            return {"status": self.status(), "reply": reason, "plan": []}

        plan = self._plan(cleaned)
        reply = plan["reply"]
        if plan["intent"] == "observe":
            observation = self.desktop.observe(session["id"])
            self._history(session["id"], "observation", observation.message, RiskLevel.SAFE, "complete")
            self._set_mode(OperatorMode.LISTENING, observation.message)
            reply = observation.message
        elif plan["intent"] == "devpilot_demo" and run_devpilot_callback:
            self._set_mode(OperatorMode.ACTING, "Running DevPilot Engineer repair workflow.")
            result = await run_devpilot_callback()
            reply = f"DevPilot Engineer finished with status {result['incident']['status']} and confidence {result['incident']['confidence']} percent."
            self._history(session["id"], "devpilot", reply, RiskLevel.SAFE, "complete")
            self._set_mode(OperatorMode.LISTENING, reply)
        elif plan["intent"] == "message":
            payload = MessageRequest(**plan["message"])
            result = self.prepare_message(payload)
            reply = result.get("message") or f"Prepared {payload.app} message for approval."
        elif plan["intent"] == "voice_message":
            payload = VoiceMessageRequest(**plan["voice_message"])
            result = self.voice_message(payload)
            reply = result.get("message") or f"Prepared voice message for {payload.recipient}."
        elif plan["intent"] == "call":
            payload = CallRequest(**plan["call"])
            result = self.start_call(payload)
            reply = result.get("message") or f"Prepared {payload.app} call for approval."
        elif plan["intent"] == "payment":
            payload = PaymentRequest(**plan["payment"])
            result = self.prepare_payment(payload)
            reply = result.get("message") or f"Prepared payment of {payload.amount:.2f} for approval."
        elif plan["intent"] == "desktop_action":
            action = DesktopActionRequest(**plan["action"])
            action_risk, action_reason = classify_desktop_action(action)
            effective_risk = RiskLevel.APPROVAL_REQUIRED if risk == RiskLevel.APPROVAL_REQUIRED else action_risk
            if effective_risk in {RiskLevel.UNCERTAIN, RiskLevel.APPROVAL_REQUIRED}:
                action_id = self._create_approval(session["id"], action.model_dump(), action_reason if action_risk != RiskLevel.SAFE else reason)
                self._set_mode(OperatorMode.WAITING_FOR_APPROVAL, "Waiting for approval before desktop action.")
                reply = f"I need approval before doing that. Approval request {action_id}: {action_reason if action_risk != RiskLevel.SAFE else reason}"
            elif effective_risk == RiskLevel.BLOCKED:
                reply = action_reason
            else:
                self._set_mode(OperatorMode.ACTING, f"Executing {action.action_type}.")
                result = self.desktop.execute(action)
                self._history(session["id"], "desktop-action", result.message, action_risk, "complete" if result.ok else "failed")
                self._set_mode(OperatorMode.LISTENING, result.message)
                reply = result.message
        elif risk == RiskLevel.APPROVAL_REQUIRED:
            self._create_approval(session["id"], {"command": cleaned, "plan": plan}, reason)
            self._set_mode(OperatorMode.WAITING_FOR_APPROVAL, "Waiting for approval before sensitive action.")
            reply = f"I need approval before this action. {reason}"
        elif plan["intent"] == "conversation":
            brain_reply = await self.assistant_reply(
                "You are Chinna, a concise local-first Windows desktop agent. "
                "Answer in one or two short sentences. Do not claim you performed actions unless a tool did it. "
                f"User said: {cleaned}"
            )
            if brain_reply and "deterministic local fallback" not in brain_reply and "failed safely" not in brain_reply:
                reply = _clean_model_reply(brain_reply)

        self.vault.store_json("transcript", f"session-{session['id']}-{_stamp()}", {"user": cleaned, "reply": reply, "plan": plan})
        return {"status": self.status(), "reply": reply, "plan": plan["steps"], "risk": risk.value}

    def observe(self) -> dict[str, Any]:
        session = self._current_session()
        if session["mode"] == OperatorMode.SLEEPING.value:
            return {"ok": False, "message": "Observation is disabled while sleeping.", "data": {}}
        result = self.desktop.observe(session["id"])
        self._history(session["id"], "observation", result.message, RiskLevel.SAFE, "complete")
        return {"ok": result.ok, "message": result.message, "data": result.data}

    def desktop_action(self, action: DesktopActionRequest) -> dict[str, Any]:
        session = self._current_session()
        if session["mode"] == OperatorMode.SLEEPING.value:
            return {"ok": False, "message": "Action blocked while sleeping.", "risk": RiskLevel.BLOCKED.value}
        risk, reason = classify_desktop_action(action)
        if risk in {RiskLevel.UNCERTAIN, RiskLevel.APPROVAL_REQUIRED}:
            action_id = self._create_approval(session["id"], action.model_dump(), reason)
            self._set_mode(OperatorMode.WAITING_FOR_APPROVAL, "Waiting for approval before desktop action.")
            return {"ok": False, "message": reason, "risk": risk.value, "approval_id": action_id}
        if risk == RiskLevel.BLOCKED:
            return {"ok": False, "message": reason, "risk": risk.value}
        self._set_mode(OperatorMode.ACTING, f"Executing {action.action_type}.")
        result = self.desktop.execute(action)
        self._history(session["id"], "desktop-action", result.message, risk, "complete" if result.ok else "failed")
        self._set_mode(OperatorMode.LISTENING, result.message)
        return {"ok": result.ok, "message": result.message, "risk": risk.value, "data": result.data}

    def approve(self, action_id: int, approved: bool) -> dict[str, Any]:
        session = self._current_session()
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM operator_approvals WHERE id = ?", (action_id,)).fetchone()
            if not row:
                return {"ok": False, "message": "Approval request not found."}
            status = "approved" if approved else "denied"
            conn.execute("UPDATE operator_approvals SET status = ? WHERE id = ?", (status, action_id))
        self._set_mode(OperatorMode.LISTENING, f"Approval {status}.")
        self._history(session["id"], "approval", f"Action {action_id} {status}.", RiskLevel.APPROVAL_REQUIRED, status)
        if not approved:
            return {"ok": True, "message": "Action denied.", "approved": False}

        try:
            action_data = json.loads(row["action_json"])
        except json.JSONDecodeError:
            return {"ok": True, "message": "Action approved, but approval payload was unreadable.", "approved": True}

        if "action_type" in action_data:
            result = self.desktop.execute(DesktopActionRequest(**action_data))
            self._history(session["id"], "approved-desktop-action", result.message, RiskLevel.APPROVAL_REQUIRED, "complete" if result.ok else "failed")
            return {"ok": result.ok, "message": result.message, "approved": True, "data": result.data}

        if action_data.get("type") == "call":
            result = self.desktop.start_supervised_call(action_data)
            self._history(session["id"], "approved-call", result.message, RiskLevel.APPROVAL_REQUIRED, "complete" if result.ok else "failed")
            return {"ok": result.ok, "message": result.message, "approved": True, "data": result.data}

        if action_data.get("type") == "message":
            result = self.desktop.start_supervised_message(action_data)
            self._history(session["id"], "approved-message", result.message, RiskLevel.APPROVAL_REQUIRED, "complete" if result.ok else "failed")
            return {"ok": result.ok, "message": result.message, "approved": True, "data": result.data}

        if action_data.get("type") == "voice-message":
            message = "Voice message approved. It is prepared with disclosure; review the recipient and send state before publishing externally."
            self._history(session["id"], "approved-voice-message", message, RiskLevel.APPROVAL_REQUIRED, "complete")
            return {"ok": True, "message": message, "approved": True, "data": action_data}

        if action_data.get("type") == "payment":
            result = self.desktop.start_supervised_payment(action_data)
            self._history(session["id"], "approved-payment", result.message, RiskLevel.APPROVAL_REQUIRED, "complete" if result.ok else "failed")
            return {"ok": result.ok, "message": result.message, "approved": True, "data": result.data}

        return {"ok": True, "message": "Action approved.", "approved": True, "data": action_data}

    def history(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM operator_history ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def current_session(self) -> dict[str, Any]:
        return self._current_session()

    def pending_approvals(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM operator_approvals WHERE status = 'pending' ORDER BY id DESC").fetchall()
        return [dict(row) for row in rows]

    def local_ai_status(self) -> dict[str, Any]:
        policy = self.operator_policy()
        return {
            "ollama": _command_available("ollama"),
            "ffmpeg": _command_available("ffmpeg"),
            "local_stt": _package_available("faster_whisper"),
            "local_tts": _package_available("pyttsx3"),
            "ocr": _package_available("pytesseract") and _command_available("tesseract"),
            "primary_model": "qwen3:8b",
            "fallback_model": "qwen3:4b",
            "cloud_available": bool(self.settings.openai_api_key),
            "cloud_enabled": policy["cloud_enabled"],
            "cloud_disabled": not policy["cloud_enabled"],
            "reasoning_mode": policy["reasoning_mode"],
            "friend_voice_clone_engine": _friend_voice_engine_name(),
        }

    async def assistant_reply(self, prompt: str) -> str:
        local_reply = await self.ollama_plan(prompt)
        policy = self.operator_policy()
        if not policy["cloud_enabled"]:
            return local_reply
        remote = await self.router.reasoning(prompt, local_reply or "I am ready.")
        return remote.content.strip() if remote.content else local_reply

    def transcribe_voice(self, payload: VoiceTranscriptionRequest) -> dict[str, Any]:
        session = self._current_session()
        if session["mode"] == OperatorMode.SLEEPING.value:
            return {"text": "", "status": "sleeping", "error": "Voice commands are ignored while sleeping.", "local": True}
        try:
            audio_bytes = base64.b64decode(payload.audio_base64.split(",", 1)[-1], validate=True)
        except (ValueError, binascii.Error):
            return {"text": "", "status": "failed", "error": "Audio payload was not valid base64.", "local": True}
        if not audio_bytes:
            return {"text": "", "status": "empty", "error": "No audio was recorded.", "local": True}

        self.vault.ensure()
        temp_dir = self.vault.root / "tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        audio_path = temp_dir / f"voice-command-{session['id']}-{_stamp()}{_audio_suffix(payload.mime_type)}"
        audio_path.write_bytes(audio_bytes)
        try:
            model = _get_whisper_model()
            language = None if payload.language_hint in {"", "auto"} else payload.language_hint
            segments, info = model.transcribe(str(audio_path), language=language, vad_filter=True)
            text = " ".join(segment.text.strip() for segment in segments).strip()
            status = "transcribed" if text else "empty"
            self._history(session["id"], "voice-input", text or "No speech detected.", RiskLevel.SAFE, status)
            self.vault.store_json(
                "voice-transcript",
                f"session-{session['id']}-{_stamp()}",
                {
                    "text": text,
                    "language": getattr(info, "language", "unknown"),
                    "duration": getattr(info, "duration", 0),
                    "mime_type": payload.mime_type,
                    "audio_stored": False,
                },
            )
            return {
                "text": text,
                "status": status,
                "language": getattr(info, "language", "unknown"),
                "duration": getattr(info, "duration", 0),
                "local": True,
            }
        except Exception as exc:
            message = f"Local transcription failed safely: {exc}"
            self._history(session["id"], "voice-input", message, RiskLevel.SAFE, "failed")
            return {"text": "", "status": "failed", "error": message, "local": True}
        finally:
            try:
                audio_path.unlink()
            except OSError:
                pass

    async def ollama_plan(self, prompt: str) -> str:
        if not _command_available("ollama"):
            return "Ollama is not installed yet; deterministic local fallback is active."
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    "http://127.0.0.1:11434/api/generate",
                    json={"model": "qwen3:8b", "prompt": prompt, "stream": False},
                )
                if response.status_code == 404:
                    response = await client.post(
                        "http://127.0.0.1:11434/api/generate",
                        json={"model": "qwen3:4b", "prompt": prompt, "stream": False},
                    )
                response.raise_for_status()
                return response.json().get("response", "").strip()
        except Exception as exc:
            return f"Local Ollama request failed safely: {exc}"

    def vault_status(self) -> dict[str, Any]:
        records = self.vault.list_records()
        folders = self.indexed_folders()
        info = self.vault.ensure()
        return {**info, "records": len(records), "indexed_folders": folders, "friend_voice": self.friend_voice_status()}

    def memory_search(self, query: str = "") -> list[dict[str, Any]]:
        records = self.vault.list_records()
        if not query:
            return records[:25]
        needle = query.lower()
        return [record for record in records if needle in json.dumps(record).lower()][:25]

    def memory_delete(self, payload: MemoryDeleteRequest) -> dict[str, Any]:
        deleted = self.vault.delete(payload.kind, payload.value)
        self._history(self._current_session()["id"], "privacy", f"Deleted {deleted} private vault file(s).", RiskLevel.APPROVAL_REQUIRED, "complete")
        return {"deleted": deleted, **self.vault.ensure()}

    def privacy_export(self) -> dict[str, Any]:
        path = self.vault.export()
        self._history(self._current_session()["id"], "privacy", f"Exported private vault to {path}.", RiskLevel.APPROVAL_REQUIRED, "complete")
        return {"ok": True, "export_path": str(path)}

    def indexed_folders(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM indexed_folders ORDER BY id ASC").fetchall()
            if not rows:
                for folder in self._review_folder_candidates():
                    conn.execute(
                        "INSERT OR IGNORE INTO indexed_folders (path, status, created_at) VALUES (?, ?, ?)",
                        (folder, "review-required", utcnow()),
                    )
                rows = conn.execute("SELECT * FROM indexed_folders ORDER BY id ASC").fetchall()
        return [dict(row) for row in rows]

    def save_indexed_folders(self, folders: list[str]) -> list[dict[str, Any]]:
        approved = {folder for folder in (_normalize_path(item) for item in folders) if folder and _is_indexable_folder(Path(folder))}
        candidates = self._review_folder_candidates()
        with self.db.connect() as conn:
            conn.execute("DELETE FROM indexed_folders")
            for folder in candidates:
                status = "approved" if folder in approved else "review-required"
                conn.execute(
                    "INSERT INTO indexed_folders (path, status, created_at) VALUES (?, ?, ?)",
                    (folder, status, utcnow()),
                )
            for folder in sorted(approved.difference(candidates)):
                conn.execute(
                    "INSERT INTO indexed_folders (path, status, created_at) VALUES (?, ?, ?)",
                    (folder, "approved", utcnow()),
                )
        self._history(
            self._current_session()["id"],
            "privacy",
            f"Saved {len(approved)} approved indexing folder(s).",
            RiskLevel.SAFE,
            "complete",
        )
        return self.indexed_folders()

    def save_friend_consent(self, payload: FriendConsentRequest) -> dict[str, Any]:
        if not payload.consent_clip_path:
            return {"status": "consent-clip-required", "message": "A consent clip path is required before friend voice can be used."}
        clip_path = Path(payload.consent_clip_path).expanduser()
        if not clip_path.exists() or not clip_path.is_file():
            return {"status": "consent-clip-missing", "message": "The consent clip path does not exist on disk."}
        record_path = self.vault.store_json(
            "friend-consent",
            payload.friend_name,
            {**payload.model_dump(), "consent_clip_path": str(clip_path)},
        )
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO friend_voice_profiles (
                    friend_name, consent_note, consent_clip_path, allowed_uses, language, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.friend_name,
                    payload.consent_note,
                    str(clip_path),
                    json.dumps(payload.allowed_uses),
                    payload.language,
                    "consent-stored",
                    utcnow(),
                ),
            )
        return {"id": cursor.lastrowid, "status": "consent-stored", "vault_record_path": str(record_path)}

    def friend_voice_status(self) -> dict[str, Any]:
        profile = self._latest_friend_voice_profile()
        clone_engine = _friend_voice_engine_name()
        consent_clip = Path(profile["consent_clip_path"]).exists() if profile and profile.get("consent_clip_path") else False
        clone_engine_available = clone_engine != "not-installed"
        return {
            "enabled": self.operator_policy()["friend_voice_enabled"],
            "consent_saved": bool(profile),
            "consent_clip_present": consent_clip,
            "friend_name": profile.get("friend_name") if profile else "",
            "language": profile.get("language") if profile else "English + Telugu",
            "clone_engine": clone_engine,
            "clone_engine_available": clone_engine_available,
            "clone_ready": bool(profile) and consent_clip and clone_engine_available,
            "fallback_voice": DEFAULT_OPERATOR_POLICY["friend_voice_fallback"],
            "disclosure_required": True,
        }

    def prepare_message(self, payload: MessageRequest) -> dict[str, Any]:
        if not payload.recipient.strip() or not payload.message.strip():
            return {"status": "invalid", "message": "Recipient and message text are required before the message flow can be prepared."}
        session_id = self._current_session()["id"]
        action_id = self._create_approval(
            session_id,
            {"type": "message", **payload.model_dump()},
            "Sending WhatsApp or other outbound messages requires approval before opening the send flow.",
        )
        self._history(session_id, "message", f"Prepared {payload.app} message for {payload.recipient}.", RiskLevel.APPROVAL_REQUIRED, "pending-approval")
        return {
            "status": "pending-approval",
            "approval_id": action_id,
            "message": f"Prepared {payload.app} message for {payload.recipient}. Approve it before the send flow opens.",
        }

    def voice_message(self, payload: VoiceMessageRequest) -> dict[str, Any]:
        if not payload.recipient.strip() or not payload.message.strip():
            return {"status": "invalid", "message": "Recipient and message text are required before the voice message flow can be prepared."}
        if payload.use_friend_voice and not self._has_friend_voice_consent():
            return {"status": "consent-required", "message": "Friend voice requires a saved consent clip before use."}
        friend_voice = self.friend_voice_status()
        risk = RiskLevel.APPROVAL_REQUIRED if payload.use_friend_voice else RiskLevel.SAFE
        disclosure = "This is Chinna using a consented AI voice. " if payload.use_friend_voice else ""
        if payload.use_friend_voice and not friend_voice["clone_ready"]:
            disclosure += "A generic local TTS fallback will be used until the local clone engine is installed. "
        session_id = self._current_session()["id"]
        action_id = self._create_approval(
            session_id,
            {"type": "voice-message", **payload.model_dump(), "disclosure": disclosure},
            "Sending messages and outgoing custom voice require approval.",
        )
        self._history(session_id, "voice-message", f"Prepared voice message for {payload.recipient}.", risk, "pending-approval")
        return {
            "status": "pending-approval",
            "approval_id": action_id,
            "disclosure": disclosure,
            "message": f"Prepared voice message for {payload.recipient}. Approve it before the send flow opens.",
        }

    def start_call(self, payload: CallRequest) -> dict[str, Any]:
        if not payload.contact_or_url.strip():
            return {"status": "invalid", "message": "A WhatsApp number, contact, or Google Meet link is required before the call flow can be prepared."}
        if payload.use_friend_voice and not self._has_friend_voice_consent():
            return {"status": "consent-required", "message": "Friend voice calls require a saved consent clip before use."}
        friend_voice = self.friend_voice_status()
        disclosure = "This call is AI-assisted and may be locally recorded by Chinna."
        if payload.use_friend_voice:
            disclosure += " Chinna is using a consented custom AI voice."
            if not friend_voice["clone_ready"]:
                disclosure += " Until the local clone engine is installed, Chinna will fall back to generic local TTS."
        record_path = self.vault.store_json("call-record", f"{payload.app}-{_stamp()}", {"request": payload.model_dump(), "disclosure": disclosure})
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO call_records (
                    app, contact_or_url, disclosure, recording_policy, status, vault_record_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.app,
                    payload.contact_or_url,
                    disclosure,
                    "transcript-and-audio-if-available",
                    "pending-approval",
                    str(record_path),
                    utcnow(),
                ),
            )
        approval_id = self._create_approval(
            self._current_session()["id"],
            {"type": "call", **payload.model_dump(), "disclosure": disclosure},
            "Every WhatsApp/Google Meet call requires approval and disclosure before joining or speaking.",
        )
        return {
            "id": cursor.lastrowid,
            "status": "pending-approval",
            "approval_id": approval_id,
            "disclosure": disclosure,
            "message": f"Prepared {payload.app} call for {payload.contact_or_url}. Approve it before the join flow opens.",
        }

    def prepare_payment(self, payload: PaymentRequest) -> dict[str, Any]:
        if not payload.recipient.strip():
            return {"status": "invalid", "message": "A payment recipient is required before the payment flow can be prepared."}
        if payload.amount <= 0:
            return {"status": "invalid", "message": "Payment amount must be greater than zero."}
        session_id = self._current_session()["id"]
        record_path = self.vault.store_json(
            "payment-request",
            f"{payload.app}-{_stamp()}",
            {"request": payload.model_dump(), "supervised": True},
        )
        approval_id = self._create_approval(
            session_id,
            {"type": "payment", **payload.model_dump(), "vault_record_path": str(record_path)},
            "Payments always require explicit approval before opening the payment flow.",
        )
        self._history(
            session_id,
            "payment",
            f"Prepared payment of {payload.amount:.2f} to {payload.recipient} in {payload.app}.",
            RiskLevel.APPROVAL_REQUIRED,
            "pending-approval",
        )
        return {
            "status": "pending-approval",
            "approval_id": approval_id,
            "message": f"Prepared payment of {payload.amount:.2f} to {payload.recipient}. Approve it before the payment flow opens.",
        }

    def _has_friend_voice_consent(self) -> bool:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id FROM friend_voice_profiles WHERE status = 'consent-stored' AND consent_clip_path IS NOT NULL ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return bool(row)

    def _latest_friend_voice_profile(self) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM friend_voice_profiles WHERE status = 'consent-stored' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def _review_folder_candidates(self) -> list[str]:
        candidates: list[Path] = []
        home = Path.home()
        roots = [home, home / "OneDrive"]
        for root in roots:
            if not root.exists() or not root.is_dir():
                continue
            try:
                for child in root.iterdir():
                    if not child.is_dir():
                        continue
                    if _is_indexable_folder(child):
                        candidates.append(child)
            except OSError:
                continue
        unique = {_normalize_path(path): path for path in candidates}
        return sorted(path for path in unique if path)

    def _plan(self, text: str) -> dict[str, Any]:
        lowered = text.lower()
        if any(term in lowered for term in ["repair demo", "devpilot", "fix error", "run repair", "sample incident"]):
            return {
                "intent": "devpilot_demo",
                "reply": "I will run DevPilot Engineer, watch the repair, and summarize the result.",
                "steps": ["Create sample incident", "Run repair agents", "Wait for resolution", "Read result"],
            }
        if any(term in lowered for term in ["look", "observe", "screen", "what is on"]):
            return {"intent": "observe", "reply": "I will observe the current screen.", "steps": ["Capture local screenshot", "Store summary in private vault"]}
        message = _message_from_text(text)
        if message:
            return {
                "intent": "message",
                "reply": "I will prepare the outbound message and hold it for approval.",
                "steps": ["Parse message target", "Require approval", "Open the supervised send flow"],
                "message": message,
            }
        voice_message = _voice_message_from_text(text)
        if voice_message:
            return {
                "intent": "voice_message",
                "reply": "I will prepare the voice message with disclosure and hold it for approval.",
                "steps": ["Parse recipient and script", "Check voice consent", "Require approval before send"],
                "voice_message": voice_message,
            }
        call = _call_from_text(text)
        if call:
            return {
                "intent": "call",
                "reply": "I will prepare the call flow and hold it for approval.",
                "steps": ["Parse app and target", "Add disclosure", "Require approval before join"],
                "call": call,
            }
        payment = _payment_from_text(text)
        if payment:
            return {
                "intent": "payment",
                "reply": "I will prepare the payment flow and hold it for approval.",
                "steps": ["Parse recipient and amount", "Require approval", "Open supervised payment flow"],
                "payment": payment,
            }
        action = _desktop_action_from_text(text)
        if action:
            return {
                "intent": "desktop_action",
                "reply": "I will perform the desktop action after safety checks.",
                "steps": ["Parse desktop action", "Apply safety policy", "Execute or request approval"],
                "action": action,
            }
        return {
            "intent": "conversation",
            "reply": "I am awake and ready. I can control the screen, prepare messages, join calls, inspect files, or run DevPilot repair.",
            "steps": ["Classify request", "Apply safety policy", "Ask for approval if needed"],
        }

    def _current_session(self) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM operator_sessions ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row)

    def _set_mode(self, mode: OperatorMode, message: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM operator_sessions ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                cursor = conn.execute(
                    "INSERT INTO operator_sessions (mode, wake_phrase, started_at, last_message) VALUES (?, ?, ?, ?)",
                    (mode.value, "Hey Chinna WakeUp", utcnow(), message),
                )
                session_id = cursor.lastrowid
            else:
                session_id = row["id"]
                conn.execute("UPDATE operator_sessions SET mode = ?, last_message = ? WHERE id = ?", (mode.value, message, session_id))
        return self._current_session()

    def _history(self, session_id: int | None, kind: str, content: str, risk_level: RiskLevel, status: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO operator_history (session_id, kind, content, risk_level, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, kind, content, risk_level.value, status, utcnow()),
            )

    def _create_approval(self, session_id: int | None, action: dict[str, Any], reason: str) -> int:
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO operator_approvals (session_id, action_json, reason, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, json.dumps(action), reason, "pending", utcnow()),
            )
        return int(cursor.lastrowid)


def _command_available(command: str) -> bool:
    if command == "ollama":
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
            Path(os.environ.get("ProgramFiles", "")) / "Ollama" / "ollama.exe",
        ]
        if any(path.exists() for path in candidates):
            return True
    elif command == "ffmpeg":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
        candidates = [
            local_app_data
            / "Microsoft"
            / "WinGet"
            / "Packages"
            / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe",
            local_app_data / "Programs" / "Gyan.FFmpeg",
            Path(os.environ.get("ProgramFiles", "")) / "Gyan.FFmpeg",
        ]
        for candidate in candidates:
            if candidate.exists() and any(candidate.rglob("ffmpeg.exe")):
                return True
    elif command == "tesseract":
        candidates = [
            Path(os.environ.get("ProgramFiles", "")) / "Tesseract-OCR" / "tesseract.exe",
            Path(os.environ.get("ProgramFiles(x86)", "")) / "Tesseract-OCR" / "tesseract.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe",
        ]
        if any(path.exists() for path in candidates):
            return True

    paths = os.environ.get("PATH", "").split(os.pathsep)
    extensions = os.environ.get("PATHEXT", ".EXE;.BAT;.CMD").split(os.pathsep)
    for path in paths:
        base = Path(path) / command
        if base.exists():
            return True
        for ext in extensions:
            if (Path(path) / f"{command}{ext.lower()}").exists() or (Path(path) / f"{command}{ext.upper()}").exists():
                return True
    return False


def _desktop_action_from_text(text: str) -> dict[str, Any] | None:
    lowered = text.lower().strip()
    url_match = re.search(r"\bopen\s+(https?://\S+)", text, re.IGNORECASE)
    if url_match:
        return {"action_type": "open-url", "url": url_match.group(1), "confidence": 95}

    search_match = re.search(r"\b(?:search|google)\s+(?:for\s+)?(.+)", text, re.IGNORECASE)
    if search_match and len(search_match.group(1).strip()) > 1:
        return {"action_type": "web-search", "text": search_match.group(1).strip(), "confidence": 90}

    if "open google" in lowered:
        return {"action_type": "open-url", "url": "https://www.google.com", "confidence": 95}

    site_aliases = {
        "youtube": "https://www.youtube.com",
        "gmail": "https://mail.google.com",
        "github": "https://github.com",
        "chatgpt": "https://chatgpt.com",
    }
    for site, url in site_aliases.items():
        if f"open {site}" in lowered:
            return {"action_type": "open-url", "url": url, "confidence": 95}

    app_match = re.search(r"\bopen\s+(notepad|calculator|calc|paint|chrome|edge|browser|whatsapp)\b", lowered)
    if app_match:
        return {"action_type": "launch-app", "target": app_match.group(1), "confidence": 90}

    click_match = re.search(r"\bclick\s+(?:at\s+)?(\d{1,4})\s*,?\s+(\d{1,4})", lowered)
    if click_match:
        return {
            "action_type": "click",
            "x": int(click_match.group(1)),
            "y": int(click_match.group(2)),
            "confidence": 85,
        }

    type_match = re.search(r"\btype\s+(.+)", text, re.IGNORECASE)
    if type_match:
        return {"action_type": "type", "text": type_match.group(1).strip(), "confidence": 80}

    hotkey_match = re.search(r"\b(?:press|hotkey)\s+([a-z0-9+ ]+)", lowered)
    if hotkey_match:
        hotkey = "+".join(part for part in hotkey_match.group(1).replace(" plus ", "+").split() if part)
        return {"action_type": "hotkey", "text": hotkey, "confidence": 85}

    if "scroll up" in lowered:
        return {"action_type": "scroll", "y": 5, "confidence": 90}
    if "scroll down" in lowered or lowered == "scroll":
        return {"action_type": "scroll", "y": -5, "confidence": 90}

    hotkey_aliases = {
        "close window": "alt+f4",
        "copy": "ctrl+c",
        "paste": "ctrl+v",
        "select all": "ctrl+a",
        "save": "ctrl+s",
        "new tab": "ctrl+t",
        "refresh page": "ctrl+r",
    }
    for phrase, hotkey in hotkey_aliases.items():
        if phrase in lowered:
            return {"action_type": "hotkey", "text": hotkey, "confidence": 90}

    click_target_match = re.search(r"\bclick\s+(?:the\s+)?(.+?)(?:\s+button)?$", text, re.IGNORECASE)
    if click_target_match and click_target_match.group(1).strip().lower() not in {"at", "there"}:
        return {"action_type": "click-target", "target": click_target_match.group(1).strip(), "confidence": 65}

    command_match = re.search(r"\brun command\s+(.+)", text, re.IGNORECASE)
    if command_match:
        return {"action_type": "run-command", "command": command_match.group(1).strip(), "confidence": 80}

    return None


def _message_from_text(text: str) -> dict[str, Any] | None:
    match = re.search(r"\bsend\s+(?:a\s+)?(?:whatsapp\s+)?message\s+to\s+(.+?)\s+(?:saying|message)\s+(.+)", text, re.IGNORECASE)
    if not match:
        return None
    return {
        "app": "WhatsApp",
        "recipient": match.group(1).strip(),
        "message": match.group(2).strip(),
    }


def _voice_message_from_text(text: str) -> dict[str, Any] | None:
    match = re.search(r"\bsend\s+(?:a\s+)?voice\s+message\s+to\s+(.+?)\s+(?:saying|message)\s+(.+)", text, re.IGNORECASE)
    if not match:
        return None
    return {
        "recipient": match.group(1).strip(),
        "message": match.group(2).strip(),
        "use_friend_voice": True,
    }


def _call_from_text(text: str) -> dict[str, Any] | None:
    whatsapp = re.search(r"\b(?:call|start\s+call\s+with)\s+(.+?)\s+(?:on|in)\s+whatsapp\b", text, re.IGNORECASE)
    if whatsapp:
        return {
            "app": "WhatsApp",
            "contact_or_url": whatsapp.group(1).strip(),
            "use_friend_voice": True,
            "record_call": True,
        }
    meet = re.search(r"\b(?:join|start)\s+(?:a\s+)?(?:google\s+)?meet\s+(.+)", text, re.IGNORECASE)
    if meet:
        return {
            "app": "Google Meet",
            "contact_or_url": meet.group(1).strip(),
            "use_friend_voice": True,
            "record_call": True,
        }
    return None


def _payment_from_text(text: str) -> dict[str, Any] | None:
    match = re.search(
        r"\bpay\s+([0-9]+(?:\.[0-9]{1,2})?)\s+to\s+(.+?)(?:\s+(?:using|via)\s+([a-zA-Z ]+?))?(?:\s+upi\s+([A-Za-z0-9.\-_@]+))?(?:\s+for\s+(.+))?$",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return {
        "amount": float(match.group(1)),
        "recipient": match.group(2).strip(),
        "app": (match.group(3) or "GPay").strip(),
        "upi_id": (match.group(4) or "").strip() or None,
        "note": (match.group(5) or "").strip(),
    }


def _normalize_command(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower())
    normalized = normalized.replace("wake up", "wakeup")
    normalized = normalized.replace("china", "chinna")
    normalized = normalized.replace("tina", "chinna")
    normalized = normalized.replace("chena", "chinna")
    return re.sub(r"\s+", " ", normalized).strip()


def _has_wake_phrase(text: str) -> bool:
    normalized = _normalize_command(text)
    return any(
        phrase in normalized
        for phrase in [
            "hey chinna wakeup",
            "ok chinna wakeup",
            "okay chinna wakeup",
            "chinna wakeup",
        ]
    )


def _remove_wake_phrase(text: str) -> str:
    normalized = _normalize_command(text)
    for phrase in ["hey chinna wakeup", "ok chinna wakeup", "okay chinna wakeup", "chinna wakeup"]:
        index = normalized.find(phrase)
        if index >= 0:
            # Use the normalized tail because speech-to-text punctuation/casing is unstable.
            return normalized[index + len(phrase) :].strip()
    return text.strip()


def _clean_model_reply(reply: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", reply, flags=re.DOTALL | re.IGNORECASE).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:500] or "I am ready."


def _package_available(package: str) -> bool:
    if importlib.util.find_spec(package) is None:
        return False
    try:
        __import__(package)
        return True
    except Exception:
        return False


def _normalize_path(path: str | Path | None) -> str:
    if not path:
        return ""
    try:
        return str(Path(path).expanduser().resolve())
    except OSError:
        return str(Path(path).expanduser())


def _is_indexable_folder(path: Path) -> bool:
    normalized = Path(_normalize_path(path))
    if not normalized.exists() or not normalized.is_dir():
        return False
    name = normalized.name.lower()
    if name.startswith(".") or name in BLOCKED_INDEX_NAMES:
        return False
    blocked_roots = [Path(os.environ.get("WINDIR", r"C:\Windows"))]
    for key, fallback in [
        ("ProgramFiles", r"C:\Program Files"),
        ("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ("ProgramData", r"C:\ProgramData"),
        ("LOCALAPPDATA", ""),
        ("APPDATA", ""),
    ]:
        value = os.environ.get(key, fallback)
        if value:
            blocked_roots.append(Path(value))
    blocked_roots.append(Path.home() / ".ssh")
    for blocked in blocked_roots:
        try:
            normalized.relative_to(blocked.resolve())
            return False
        except Exception:
            continue
    try:
        if normalized == Path.home().resolve():
            return False
    except OSError:
        pass
    lowered = str(normalized).lower()
    if any(token in lowered for token in ["\\cache", "\\cookies", "\\credentials", "\\browser", "\\profile"]):
        return False
    return True


def _friend_voice_engine_name() -> str:
    if _package_available("TTS"):
        return "coqui-tts"
    return "not-installed"


def _audio_suffix(mime_type: str) -> str:
    lowered = mime_type.lower()
    if "wav" in lowered:
        return ".wav"
    if "mpeg" in lowered or "mp3" in lowered:
        return ".mp3"
    if "ogg" in lowered:
        return ".ogg"
    if "mp4" in lowered:
        return ".m4a"
    return ".webm"


def _get_whisper_model() -> Any:
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        from faster_whisper import WhisperModel

        _WHISPER_MODEL = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _WHISPER_MODEL


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
