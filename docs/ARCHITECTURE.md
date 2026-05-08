# DevPilot AI Architecture

DevPilot AI is built as a local full-stack system with optional cloud integrations.

## Flow

1. Incident enters through the dashboard or API.
2. Backend creates a SQLite incident record.
3. Workflow copies the target repo into an isolated runtime workspace.
4. Test Runner captures the baseline failure.
5. Log Analyzer classifies severity and root cause.
6. Memory Agent searches known fixes.
7. Code Fixer applies a minimal patch.
8. Test Runner verifies the patch.
9. Manager retries up to three attempts if tests fail.
10. Reviewer, Security Guardrail, Rollback Planner, PR Writer, and Voice Briefing agents produce final evidence.

## OpenAI Model Routing

- `gpt-5.5` is routed to reasoning, planning, review, guardrail, PR writing, and briefing work.
- `gpt-5.1-codex-max` is routed to code repair work.
- If `OPENAI_API_KEY` is missing, deterministic fallbacks keep the complete judging flow runnable.

## Safety

- All edits occur in `runtime/workspaces`.
- Risky file patterns such as secrets, auth, payment, token, and `.env` trigger a high-risk review.
- A real GitHub PR requires explicit approval.
- Missing credentials produce a PR draft preview instead of failing.
