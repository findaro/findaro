from __future__ import annotations

import httpx

from findaro.llm.base import LLMError


class AnthropicLLM:
    """Minimal Messages API client (no SDK dependency)."""

    def __init__(self, api_key: str, model: str, timeout: float = 300.0):
        self.name = f"anthropic:{model}"
        self.model = model
        self._client = httpx.AsyncClient(
            base_url="https://api.anthropic.com",
            timeout=timeout,
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        )

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        if json_mode:
            prompt += "\n\nRespond with JSON only, no prose."
        body: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        try:
            resp = await self._client.post("/v1/messages", json=body)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"anthropic request failed: {e}") from e
        data = resp.json()
        return "".join(block.get("text", "") for block in data.get("content", []))

    async def aclose(self) -> None:
        await self._client.aclose()
