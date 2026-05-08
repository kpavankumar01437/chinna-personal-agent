from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import IncidentStatus, Severity


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    confidence INTEGER NOT NULL DEFAULT 0,
                    root_cause TEXT NOT NULL DEFAULT '',
                    time_saved_minutes INTEGER NOT NULL DEFAULT 0,
                    repo_path TEXT,
                    workspace_path TEXT,
                    test_command TEXT NOT NULL,
                    logs TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id INTEGER NOT NULL,
                    agent_name TEXT NOT NULL,
                    step_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS repair_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id INTEGER NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    patch_summary TEXT NOT NULL,
                    test_command TEXT NOT NULL,
                    test_result TEXT NOT NULL,
                    logs TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mistakes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id INTEGER NOT NULL,
                    agent_name TEXT NOT NULL,
                    mistake TEXT NOT NULL,
                    cause TEXT NOT NULL,
                    attempted_action TEXT NOT NULL,
                    result TEXT NOT NULL,
                    final_resolution TEXT NOT NULL,
                    prevention_note TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS security_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id INTEGER NOT NULL,
                    risk_level TEXT NOT NULL,
                    risky_files TEXT NOT NULL,
                    blocked_reason TEXT NOT NULL,
                    approval_required INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rollback_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id INTEGER NOT NULL UNIQUE,
                    affected_files TEXT NOT NULL,
                    revert_steps TEXT NOT NULL,
                    rollback_command TEXT NOT NULL,
                    risk_notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_base (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    error_signature TEXT NOT NULL UNIQUE,
                    root_cause TEXT NOT NULL,
                    fix_summary TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    reuse_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pr_drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id INTEGER NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    commit_hash TEXT NOT NULL,
                    diff_summary TEXT NOT NULL,
                    status TEXT NOT NULL,
                    pr_url TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def create_incident(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO incidents (
                    title, source_type, status, severity, confidence, root_cause,
                    time_saved_minutes, repo_path, workspace_path, test_command,
                    logs, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["title"],
                    payload["source_type"],
                    IncidentStatus.DETECTED.value,
                    Severity.MEDIUM.value,
                    0,
                    "",
                    0,
                    payload.get("repo_path"),
                    payload.get("workspace_path"),
                    payload["test_command"],
                    payload.get("logs", ""),
                    now,
                    now,
                ),
            )
            incident_id = cursor.lastrowid
        return self.get_incident(incident_id)

    def update_incident(self, incident_id: int, **fields: Any) -> dict[str, Any]:
        fields["updated_at"] = utcnow()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [incident_id]
        with self.connect() as conn:
            conn.execute(f"UPDATE incidents SET {assignments} WHERE id = ?", values)
        return self.get_incident(incident_id)

    def get_incident(self, incident_id: int) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if not row:
            raise KeyError(f"Incident {incident_id} not found")
        return dict(row)

    def list_incidents(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM incidents ORDER BY id DESC").fetchall()
        return [dict(row) for row in rows]

    def add_event(self, incident_id: int, agent_name: str, step_type: str, message: str, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_events (incident_id, agent_name, step_type, message, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (incident_id, agent_name, step_type, message, status, utcnow()),
            )

    def add_attempt(self, incident_id: int, attempt_number: int, patch_summary: str, test_command: str, test_result: str, logs: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO repair_attempts (
                    incident_id, attempt_number, patch_summary, test_command, test_result, logs, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (incident_id, attempt_number, patch_summary, test_command, test_result, logs, utcnow()),
            )

    def add_mistake(
        self,
        incident_id: int,
        agent_name: str,
        mistake: str,
        cause: str,
        attempted_action: str,
        result: str,
        final_resolution: str,
        prevention_note: str,
        status: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO mistakes (
                    incident_id, agent_name, mistake, cause, attempted_action, result,
                    final_resolution, prevention_note, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    incident_id,
                    agent_name,
                    mistake,
                    cause,
                    attempted_action,
                    result,
                    final_resolution,
                    prevention_note,
                    status,
                    utcnow(),
                ),
            )

    def add_security_review(self, incident_id: int, risk_level: str, risky_files: list[str], blocked_reason: str, approval_required: bool) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO security_reviews (
                    incident_id, risk_level, risky_files, blocked_reason, approval_required, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (incident_id, risk_level, json.dumps(risky_files), blocked_reason, int(approval_required), utcnow()),
            )

    def upsert_rollback_plan(self, incident_id: int, affected_files: list[str], revert_steps: list[str], rollback_command: str, risk_notes: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO rollback_plans (
                    incident_id, affected_files, revert_steps, rollback_command, risk_notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    affected_files = excluded.affected_files,
                    revert_steps = excluded.revert_steps,
                    rollback_command = excluded.rollback_command,
                    risk_notes = excluded.risk_notes,
                    created_at = excluded.created_at
                """,
                (incident_id, json.dumps(affected_files), json.dumps(revert_steps), rollback_command, risk_notes, utcnow()),
            )

    def upsert_memory(self, error_signature: str, root_cause: str, fix_summary: str, outcome: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_base (error_signature, root_cause, fix_summary, outcome, reuse_count, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(error_signature) DO UPDATE SET
                    root_cause = excluded.root_cause,
                    fix_summary = excluded.fix_summary,
                    outcome = excluded.outcome,
                    reuse_count = knowledge_base.reuse_count + 1
                """,
                (error_signature, root_cause, fix_summary, outcome, utcnow()),
            )

    def upsert_pr_draft(self, incident_id: int, title: str, body: str, branch: str, commit_hash: str, diff_summary: str, status: str, pr_url: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO pr_drafts (
                    incident_id, title, body, branch, commit_hash, diff_summary, status, pr_url, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    title = excluded.title,
                    body = excluded.body,
                    branch = excluded.branch,
                    commit_hash = excluded.commit_hash,
                    diff_summary = excluded.diff_summary,
                    status = excluded.status,
                    pr_url = excluded.pr_url,
                    created_at = excluded.created_at
                """,
                (incident_id, title, body, branch, commit_hash, diff_summary, status, pr_url, utcnow()),
            )

    def set_setting(self, key: str, value: Any) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def incident_detail(self, incident_id: int, diff: str = "", voice_briefing: str = "") -> dict[str, Any]:
        with self.connect() as conn:
            tables = {
                "events": "SELECT * FROM agent_events WHERE incident_id = ? ORDER BY id ASC",
                "attempts": "SELECT * FROM repair_attempts WHERE incident_id = ? ORDER BY attempt_number ASC",
                "mistakes": "SELECT * FROM mistakes WHERE incident_id = ? ORDER BY id ASC",
                "security_reviews": "SELECT * FROM security_reviews WHERE incident_id = ? ORDER BY id ASC",
                "rollback_plan": "SELECT * FROM rollback_plans WHERE incident_id = ?",
                "pr_draft": "SELECT * FROM pr_drafts WHERE incident_id = ?",
            }
            incident = self.get_incident(incident_id)
            detail: dict[str, Any] = {"incident": incident}
            for key, sql in tables.items():
                if key in {"rollback_plan", "pr_draft"}:
                    row = conn.execute(sql, (incident_id,)).fetchone()
                    detail[key] = dict(row) if row else None
                else:
                    detail[key] = [dict(row) for row in conn.execute(sql, (incident_id,)).fetchall()]
            kb_rows = conn.execute("SELECT * FROM knowledge_base ORDER BY id DESC LIMIT 8").fetchall()
            detail["memory"] = [dict(row) for row in kb_rows]
        for review in detail["security_reviews"]:
            review["risky_files"] = json.loads(review["risky_files"])
            review["approval_required"] = bool(review["approval_required"])
        if detail["rollback_plan"]:
            detail["rollback_plan"]["affected_files"] = json.loads(detail["rollback_plan"]["affected_files"])
            detail["rollback_plan"]["revert_steps"] = json.loads(detail["rollback_plan"]["revert_steps"])
        detail["diff"] = diff
        detail["voice_briefing"] = voice_briefing
        return detail

    def search_memory(self, query: str) -> list[dict[str, Any]]:
        needle = f"%{query.lower()}%"
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM knowledge_base
                WHERE lower(error_signature) LIKE ? OR lower(root_cause) LIKE ? OR lower(fix_summary) LIKE ?
                ORDER BY reuse_count DESC, id DESC
                LIMIT 10
                """,
                (needle, needle, needle),
            ).fetchall()
        return [dict(row) for row in rows]
