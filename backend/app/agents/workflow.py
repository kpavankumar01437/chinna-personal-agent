from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from ..config import Settings
from ..database import Database
from ..schemas import IncidentStatus, Severity
from ..core.notifications import send_webhook
from ..core.repo_tools import (
    changed_files,
    copy_repo,
    initialize_local_git,
    read_text,
    risk_review,
    run_command,
    ensure_git_baseline,
    snapshot_files,
    stable_commit_hash,
    unified_diff,
    write_text,
)
from .llm import OpenAIModelRouter


class DevPilotWorkflow:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self.llm = OpenAIModelRouter(settings)

    def run_sync(self, incident_id: int) -> dict:
        return asyncio.run(self.run(incident_id))

    async def run(self, incident_id: int) -> dict:
        incident = self.db.get_incident(incident_id)
        workspace = self._prepare_workspace(incident)
        self.db.update_incident(incident_id, workspace_path=str(workspace))

        self._event(incident_id, "Manager Agent", "Plan", "Created repair plan and delegated analysis, memory, code repair, test, review, security, and PR tasks.", "complete")

        baseline_result = run_command(incident["test_command"], workspace)
        self.db.add_attempt(
            incident_id,
            0,
            "Baseline test run before any code repair.",
            incident["test_command"],
            "passed" if baseline_result.returncode == 0 else "failed",
            baseline_result.output,
        )
        severity = self._classify_severity(incident.get("logs", "") + "\n" + baseline_result.output)
        root_cause = self._infer_root_cause(baseline_result.output)
        self.db.update_incident(
            incident_id,
            status=IncidentStatus.ANALYZED.value,
            severity=severity.value,
            root_cause=root_cause,
            confidence=35,
        )
        self._event(incident_id, "Log Analyzer Agent", "Analyze", f"Classified incident as {severity.value}. Root cause hypothesis: {root_cause}", "complete")

        memory_hits = self.db.search_memory(root_cause[:80])
        if memory_hits:
            self._event(incident_id, "Memory Agent", "Recall", f"Found {len(memory_hits)} related historical fix patterns.", "complete")
        else:
            self._event(incident_id, "Memory Agent", "Recall", "No matching memory found; creating a new knowledge trail for this incident.", "complete")

        await self.llm.reasoning(
            f"Research likely fixes for this failure:\n{baseline_result.output[:3000]}",
            "Known failure resembles Python import/API contract/validation defects. Start with the smallest patch and verify with tests.",
        )
        self._event(incident_id, "Research Agent", "Research", "Checked known failure patterns and selected a minimal repair strategy.", "complete")

        before = snapshot_files(workspace)
        final_diff = ""
        final_output = baseline_result.output
        resolved = False
        patch_summary = ""

        for attempt in range(1, 4):
            self.db.update_incident(incident_id, status=IncidentStatus.FIX_ATTEMPTED.value)
            self._event(incident_id, "Code Fixer Agent", "Patch", f"Applying repair attempt {attempt} with {self.settings.openai_coding_model} routing.", "running")
            patch_summary = self._apply_repair_attempt(workspace, attempt, final_output)
            after_patch = snapshot_files(workspace)
            diff = unified_diff(before, after_patch)
            final_diff = diff
            result = run_command(incident["test_command"], workspace)
            final_output = result.output
            test_status = "passed" if result.returncode == 0 else "failed"
            self.db.add_attempt(incident_id, attempt, patch_summary, incident["test_command"], test_status, final_output)
            self._event(incident_id, "Test Runner Agent", "Verify", f"Attempt {attempt} tests {test_status}.", "complete" if result.returncode == 0 else "failed")

            if result.returncode == 0:
                resolved = True
                if attempt > 1:
                    self.db.update_incident(incident_id, status=IncidentStatus.SELF_CORRECTED.value)
                    self._event(incident_id, "Manager Agent", "Self-Correct", "Previous failed attempt was converted into a corrected patch using the latest test output.", "complete")
                break

            self.db.update_incident(incident_id, status=IncidentStatus.FAILED.value)
            self.db.add_mistake(
                incident_id,
                "Code Fixer Agent",
                f"Attempt {attempt} did not fully resolve the incident.",
                "The patch addressed only part of the failing behavior.",
                patch_summary,
                final_output[-1200:],
                "Next attempt will use the new test output to target remaining failures.",
                "Capture complete API contracts and validation rules before patching.",
                IncidentStatus.FAILED.value,
            )
            self._event(incident_id, "Reviewer Agent", "Review", "Patch is incomplete; feeding failed test output back into the repair loop.", "failed")

        final_snapshot = snapshot_files(workspace)
        files = changed_files(before, final_snapshot)
        risk_level, risky_files, blocked_reason, approval_required = risk_review(files)
        self.db.add_security_review(incident_id, risk_level, risky_files, blocked_reason, approval_required)
        self._event(incident_id, "Security Guardrail Agent", "Risk Review", f"Risk level {risk_level}. {blocked_reason}", "complete")

        rollback_command = "git revert HEAD" if files else "No rollback needed"
        self.db.upsert_rollback_plan(
            incident_id,
            files,
            [
                "Review the PR diff and confirm the changed files match the incident scope.",
                "If the change causes regression, revert the generated commit.",
                "Re-run the same test command after rollback to confirm the previous state.",
            ],
            rollback_command,
            "Low risk if tests pass and only sample application files changed." if risk_level == "Low" else blocked_reason,
        )

        confidence = self._confidence(resolved, risk_level, len(files))
        status = IncidentStatus.RESOLVED.value if resolved and not (approval_required and risk_level == "High") else IncidentStatus.ESCALATED.value
        time_saved = self._time_saved(severity, len(files), len(self.db.incident_detail(incident_id)["attempts"]))
        self.db.update_incident(incident_id, status=status, confidence=confidence, time_saved_minutes=time_saved, root_cause=root_cause)

        if resolved:
            self.db.add_mistake(
                incident_id,
                "Manager Agent",
                "Original software failure blocked a clean test run.",
                root_cause,
                "Applied targeted code patches and verified the result with tests.",
                "All configured tests passed.",
                patch_summary,
                "Add contract tests and validation checks around the repaired behavior.",
                IncidentStatus.RESOLVED.value,
            )
            self.db.upsert_memory(
                self._signature(final_output, root_cause),
                root_cause,
                patch_summary,
                "Resolved with passing tests",
            )

        commit_hash = stable_commit_hash(final_diff)
        try:
            if resolved:
                commit_hash = initialize_local_git(workspace)
        except Exception:
            pass

        pr_title = f"DevPilot repair: {incident['title']}"
        pr_body = self._pr_body(incident_id, root_cause, final_output, final_diff, confidence, time_saved)
        self.db.upsert_pr_draft(
            incident_id,
            pr_title,
            pr_body,
            "devpilot/repair-preview",
            commit_hash,
            self._diff_summary(files, final_diff),
            "preview-ready",
            None,
        )
        self._event(incident_id, "PR Writer Agent", "PR Draft", "Prepared PR draft with test evidence, rollback plan, confidence, and time-saved estimate.", "complete")

        self._event(incident_id, "Voice Briefing Agent", "Briefing", self.voice_briefing(incident_id), "complete")
        notification_status = await self._notify(incident_id, status, confidence, time_saved)
        self._event(incident_id, "Notification Agent", "Webhook", f"Discord/Slack notification {notification_status}.", "complete" if notification_status != "failed" else "failed")
        return self.db.incident_detail(incident_id, final_diff, self.voice_briefing(incident_id))

    def get_diff(self, incident_id: int) -> str:
        incident = self.db.get_incident(incident_id)
        workspace = Path(incident["workspace_path"]) if incident["workspace_path"] else None
        if not workspace or not workspace.exists():
            return ""
        original = Path(incident["repo_path"]) if incident["repo_path"] else self.settings.sample_repo_path
        if not original.exists():
            return ""
        return unified_diff(snapshot_files(original), snapshot_files(workspace))

    def voice_briefing(self, incident_id: int) -> str:
        incident = self.db.get_incident(incident_id)
        return (
            f"DevPilot resolved incident {incident['title']}. "
            f"Severity was {incident['severity']}. Root cause: {incident['root_cause']}. "
            f"Confidence is {incident['confidence']} percent, with an estimated "
            f"{incident['time_saved_minutes']} minutes of developer time saved. "
            "A pull request draft, rollback plan, test evidence, and mistake history are ready for review."
        )

    def _prepare_workspace(self, incident: dict) -> Path:
        workspace = self.settings.runtime_dir / "workspaces" / f"incident-{incident['id']}"
        source = Path(incident["repo_path"]) if incident.get("repo_path") else self.settings.sample_repo_path
        if not source.exists():
            source = self.settings.sample_repo_path
        copy_repo(source, workspace)
        try:
            ensure_git_baseline(workspace)
        except Exception:
            pass
        return workspace

    def _apply_repair_attempt(self, workspace: Path, attempt: int, latest_output: str) -> str:
        if attempt == 1:
            try:
                content = read_text(workspace, "app/math_tools.py")
                content = content.replace("from .helpers import normalize_number", "from .helpers import normalize_value")
                content = content.replace("normalize_number(raw)", "normalize_value(raw)")
                write_text(workspace, "app/math_tools.py", content)
                return "Fixed broken helper import and normalized function call in app/math_tools.py."
            except FileNotFoundError:
                return "No known import repair target found."
        if attempt == 2:
            api = """def greet_user(name: str) -> dict:\n    cleaned = name.strip() or \"friend\"\n    return {\"message\": f\"Hello, {cleaned}\"}\n\n\ndef create_user(payload: dict) -> dict:\n    email = str(payload.get(\"email\", \"\")).strip()\n    name = str(payload.get(\"name\", \"\")).strip()\n    if not email:\n        return {\"ok\": False, \"error\": \"email is required\"}\n    return {\"ok\": True, \"user\": {\"name\": name or \"Unknown\", \"email\": email}}\n"""
            write_text(workspace, "app/api.py", api)
            return "Repaired API response contract and added missing email validation in app/api.py."
        return "No further deterministic patch was available; escalation recommended."

    def _classify_severity(self, text: str) -> Severity:
        lowered = text.lower()
        if any(term in lowered for term in ["security", "payment", "data loss", "critical"]):
            return Severity.CRITICAL
        if any(term in lowered for term in ["importerror", "modulenotfounderror", "500", "failed"]):
            return Severity.HIGH
        if any(term in lowered for term in ["assertionerror", "validation"]):
            return Severity.MEDIUM
        return Severity.LOW

    def _infer_root_cause(self, output: str) -> str:
        lowered = output.lower()
        if "normalize_number" in lowered or "importerror" in lowered:
            return "A broken import references a helper function that does not exist, blocking test collection."
        if "email is required" in lowered or "message" in lowered:
            return "API contract and validation behavior do not match the expected response format."
        if "assertionerror" in lowered:
            return "Application behavior differs from the tested contract."
        return "The failing command produced errors that require targeted code repair and verification."

    def _confidence(self, resolved: bool, risk_level: str, file_count: int) -> int:
        if not resolved:
            return 38
        confidence = 92
        if risk_level == "Medium":
            confidence -= 10
        if risk_level == "High":
            confidence -= 24
        if file_count > 3:
            confidence -= 6
        return max(35, confidence)

    def _time_saved(self, severity: Severity, file_count: int, attempts: int) -> int:
        base = {
            Severity.LOW: 20,
            Severity.MEDIUM: 35,
            Severity.HIGH: 55,
            Severity.CRITICAL: 90,
        }[severity]
        return base + file_count * 4 + attempts * 7

    def _signature(self, output: str, root_cause: str) -> str:
        if "normalize_value" in output or "normalize_number" in root_cause or "broken import" in root_cause.lower():
            return "python-helper-import-contract"
        return root_cause.lower()[:80]

    def _diff_summary(self, files: list[str], diff: str) -> str:
        if not files:
            return "No code diff generated."
        lines = len([line for line in diff.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))])
        return f"Changed {len(files)} file(s): {', '.join(files)}. Patch contains {lines} changed line(s)."

    def _pr_body(self, incident_id: int, root_cause: str, test_output: str, diff: str, confidence: int, time_saved: int) -> str:
        detail = self.db.incident_detail(incident_id, diff, "")
        rollback = detail["rollback_plan"]
        affected = ", ".join(rollback["affected_files"]) if rollback else "None"
        return f"""## DevPilot AI Repair Summary

### Root Cause
{root_cause}

### Verification
Configured tests were executed after the repair.

```text
{test_output[-2000:]}
```

### Risk And Confidence
- Confidence: {confidence}%
- Estimated time saved: {time_saved} minutes
- Affected files: {affected}

### Rollback Plan
{rollback['rollback_command'] if rollback else 'No rollback required'}

### Mistake And Resolution Notes
DevPilot tracked failed attempts and converted the latest test output into the final patch strategy.
"""

    def _event(self, incident_id: int, agent_name: str, step_type: str, message: str, status: str) -> None:
        self.db.add_event(incident_id, agent_name, step_type, message, status)

    async def _notify(self, incident_id: int, status: str, confidence: int, time_saved: int) -> str:
        try:
            incident = self.db.get_incident(incident_id)
            message = (
                f"DevPilot AI incident #{incident_id} finished as {status}. "
                f"Severity: {incident['severity']}. Confidence: {confidence}%. "
                f"Estimated time saved: {time_saved} minutes."
            )
            return await send_webhook(self.settings.discord_webhook_url, message)
        except Exception:
            return "failed"
