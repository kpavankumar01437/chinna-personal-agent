from pathlib import Path

from app.agents.workflow import DevPilotWorkflow
from app.config import Settings
from app.core.repo_tools import risk_review
from app.database import Database


def make_workflow(tmp_path: Path) -> tuple[Database, DevPilotWorkflow, Settings]:
    root = Path(__file__).resolve().parents[3]
    settings = Settings(_env_file=None)
    settings.runtime_dir = tmp_path / "runtime"
    settings.db_path = settings.runtime_dir / "test.sqlite3"
    settings.sample_repo_path = root / "sample-repo"
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.db_path)
    return db, DevPilotWorkflow(db, settings), settings


def test_workflow_repairs_sample_repo_end_to_end(tmp_path):
    db, workflow, settings = make_workflow(tmp_path)
    incident = db.create_incident(
        {
            "title": "Sample failure",
            "source_type": "sample",
            "logs": "pytest failure",
            "repo_path": str(settings.sample_repo_path),
            "test_command": "python -m pytest",
        }
    )

    detail = workflow.run_sync(incident["id"])

    assert detail["incident"]["status"] == "Resolved"
    assert detail["incident"]["severity"] == "High"
    assert detail["incident"]["confidence"] >= 80
    assert len(detail["attempts"]) == 3
    assert detail["attempts"][0]["test_result"] == "failed"
    assert detail["attempts"][0]["patch_summary"] == "Baseline test run before any code repair."
    assert detail["attempts"][1]["test_result"] == "failed"
    assert detail["attempts"][2]["test_result"] == "passed"
    assert detail["mistakes"]
    assert detail["rollback_plan"]["affected_files"] == ["app/api.py", "app/math_tools.py"]
    assert detail["pr_draft"]["status"] == "preview-ready"
    assert "app/api.py" in detail["diff"]
    assert "app/math_tools.py" in detail["diff"]


def test_security_guardrail_flags_sensitive_files(tmp_path):
    risk_level, risky_files, blocked_reason, approval_required = risk_review(["app/auth.py", ".env"])

    assert risk_level == "High"
    assert risky_files == ["app/auth.py", ".env"]
    assert "sensitive" in blocked_reason
    assert approval_required is True


def test_memory_search_records_resolution(tmp_path):
    db, workflow, settings = make_workflow(tmp_path)
    incident = db.create_incident(
        {
            "title": "Sample failure",
            "source_type": "sample",
            "logs": "pytest failure",
            "repo_path": str(settings.sample_repo_path),
            "test_command": "python -m pytest",
        }
    )

    workflow.run_sync(incident["id"])
    rows = db.search_memory("python")

    assert rows
    assert rows[0]["outcome"] == "Resolved with passing tests"
