from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from zerch.llm.base import LLMError


class OllamaLLM:
    def __init__(self, base_url: str, model: str, timeout: float = 300.0):
        self.name = f"ollama:{model}"
        self.model = model
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body: dict = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": "30m",  # keep the model loaded between requests (a cold load costs seconds)
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_mode:
            body["format"] = "json"
        try:
            resp = await self._client.post("/api/chat", json=body)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"ollama request failed: {e}") from e
        return resp.json()["message"]["content"]

    async def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 400,
    ) -> AsyncIterator[str]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = {"model": self.model, "messages": messages, "stream": True, "keep_alive": "30m",
                "options": {"temperature": temperature, "num_predict": max_tokens}}
        try:
            async with self._client.stream("POST", "/api/chat", json=body) as resp:
                if resp.status_code >= 400:
                    raise LLMError(f"ollama stream failed: {resp.status_code} {(await resp.aread())[:300]!r}")
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    delta = (chunk.get("message") or {}).get("content")
                    if delta:
                        yield delta
                    if chunk.get("done"):
                        break
        except httpx.HTTPError as e:
            raise LLMError(f"ollama stream failed: {e}") from e

    async def aclose(self) -> None:
        await self._client.aclose()
