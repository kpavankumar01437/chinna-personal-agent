# GitHub Automation Setup

DevPilot AI has two GitHub automation layers.

## 1. Repository CI

The workflow in `.github/workflows/ci.yml` runs on push, pull request, and manual dispatch.

It checks:

- Backend agent workflow tests.
- Frontend dashboard production build.

This gives judges visible proof that the project is maintained like a real engineering system.

## 2. DevPilot PR Automation

The app can prepare a PR preview without credentials. To create real PRs, configure:

```text
GITHUB_TOKEN=
GITHUB_OWNER=
GITHUB_REPO=
GITHUB_BASE_BRANCH=main
```

You can also enter owner, repo, base branch, and token from the dashboard's **GitHub Settings** panel.

Required token permission:

- Fine-grained token with repository contents and pull request write access.

## Push This Project To GitHub

After creating an empty GitHub repo, run:

```powershell
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git branch -M main
git push -u origin main
```

If the remote already exists:

```powershell
git remote set-url origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

## Recommended Repository Name

```text
devpilot-ai-agentathon
```
