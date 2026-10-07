from __future__ import annotations

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

    async def aclose(self) -> None:
        await self._client.aclose()
