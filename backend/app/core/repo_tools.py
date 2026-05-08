from __future__ import annotations

import difflib
import hashlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


RISKY_PATTERNS = (
    ".env",
    "secret",
    "token",
    "password",
    "auth",
    "payment",
    "billing",
    "credentials",
)


@dataclass
class CommandResult:
    returncode: int
    output: str


def copy_repo(source: Path, destination: Path) -> Path:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".git"))
    return destination


def snapshot_files(repo_path: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in repo_path.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and ".pytest_cache" not in path.parts and ".git" not in path.parts:
            rel = path.relative_to(repo_path).as_posix()
            snapshot[rel] = path.read_text(encoding="utf-8")
    return snapshot


def unified_diff(before: dict[str, str], after: dict[str, str]) -> str:
    chunks: list[str] = []
    for rel in sorted(set(before) | set(after)):
        old = before.get(rel, "").splitlines(keepends=True)
        new = after.get(rel, "").splitlines(keepends=True)
        if old == new:
            continue
        chunks.extend(
            difflib.unified_diff(
                old,
                new,
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
                lineterm="",
            )
        )
        chunks.append("\n")
    return "".join(chunks).strip()


def changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(rel for rel in set(before) | set(after) if before.get(rel) != after.get(rel))


def run_command(command: str, cwd: Path, timeout: int = 40) -> CommandResult:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(cwd)
    if command == "python" or command.startswith("python "):
        command = f'"{sys.executable}"{command[len("python"):]}'
    completed = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    return CommandResult(completed.returncode, output.strip())


def write_text(repo_path: Path, relative_path: str, content: str) -> None:
    path = repo_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def read_text(repo_path: Path, relative_path: str) -> str:
    return (repo_path / relative_path).read_text(encoding="utf-8")


def risk_review(files: list[str]) -> tuple[str, list[str], str, bool]:
    risky = [name for name in files if any(pattern in name.lower() for pattern in RISKY_PATTERNS)]
    if risky:
        return (
            "High",
            risky,
            "Patch touches sensitive areas such as secrets, authentication, payments, or credentials.",
            True,
        )
    if len(files) > 5:
        return ("Medium", files, "Patch touches many files and should be reviewed before PR creation.", True)
    return ("Low", [], "No sensitive file patterns detected.", False)


def stable_commit_hash(diff: str) -> str:
    if not diff:
        return "preview-no-diff"
    return hashlib.sha1(diff.encode("utf-8")).hexdigest()[:12]


def ensure_git_baseline(repo_path: Path) -> None:
    if not (repo_path / ".git").exists():
        subprocess.run("git init", cwd=repo_path, shell=True, capture_output=True, text=True)
        subprocess.run('git config user.email "devpilot@example.local"', cwd=repo_path, shell=True, capture_output=True, text=True)
        subprocess.run('git config user.name "DevPilot AI"', cwd=repo_path, shell=True, capture_output=True, text=True)
        subprocess.run("git add .", cwd=repo_path, shell=True, capture_output=True, text=True)
        subprocess.run('git commit -m "baseline before DevPilot repair"', cwd=repo_path, shell=True, capture_output=True, text=True)


def initialize_local_git(repo_path: Path) -> str:
    ensure_git_baseline(repo_path)
    branch = "devpilot/repair-preview"
    subprocess.run(f"git checkout -B {branch}", cwd=repo_path, shell=True, capture_output=True, text=True)
    subprocess.run("git add .", cwd=repo_path, shell=True, capture_output=True, text=True)
    subprocess.run('git commit -m "DevPilot autonomous repair"', cwd=repo_path, shell=True, capture_output=True, text=True)
    result = subprocess.run("git rev-parse --short HEAD", cwd=repo_path, shell=True, capture_output=True, text=True)
    return result.stdout.strip() or "preview-no-commit"
