from __future__ import annotations

import httpx


async def send_webhook(webhook_url: str | None, message: str) -> str:
    if not webhook_url:
        return "skipped"

    payload = {"text": message}
    if "discord" in webhook_url.lower():
        payload = {"content": message}

    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.post(webhook_url, json=payload)
        response.raise_for_status()
    return "sent"
