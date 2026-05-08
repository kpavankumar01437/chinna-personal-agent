from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import Settings


@dataclass
class LLMResult:
    model: str
    content: str
    used_remote_model: bool


class OpenAIModelRouter:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def reasoning(self, prompt: str, fallback: str) -> LLMResult:
        return await self._call(self.settings.openai_reasoning_model, prompt, fallback)

    async def coding(self, prompt: str, fallback: str) -> LLMResult:
        return await self._call(self.settings.openai_coding_model, prompt, fallback)

    async def structured(self, prompt: str, fallback: dict[str, Any]) -> dict[str, Any]:
        result = await self.reasoning(prompt, json.dumps(fallback))
        try:
            return json.loads(result.content)
        except json.JSONDecodeError:
            return fallback

    async def _call(self, model: str, prompt: str, fallback: str) -> LLMResult:
        if not self.settings.openai_api_key:
            return LLMResult(model=model, content=fallback, used_remote_model=False)
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(
                    "https://api.openai.com/v1/responses",
                    headers={
                        "Authorization": f"Bearer {self.settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "input": prompt,
                    },
                )
                response.raise_for_status()
                data = response.json()
                return LLMResult(model=model, content=_extract_text(data) or fallback, used_remote_model=True)
        except Exception:
            return LLMResult(model=model, content=fallback, used_remote_model=False)


def _extract_text(data: dict[str, Any]) -> str:
    if "output_text" in data:
        return data["output_text"]
    parts: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                parts.append(content.get("text", ""))
    return "\n".join(part for part in parts if part).strip()
