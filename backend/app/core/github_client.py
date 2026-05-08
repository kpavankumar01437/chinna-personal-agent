from __future__ import annotations

import httpx


async def create_pull_request(
    token: str,
    owner: str,
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str,
) -> str:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {"title": title, "body": body, "head": head, "base": base}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(f"https://api.github.com/repos/{owner}/{repo}/pulls", headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["html_url"]
