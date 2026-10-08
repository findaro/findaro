from __future__ import annotations

import httpx

from zerch.llm.base import LLMError


class OpenAILLM:
    """Minimal Chat Completions client (no SDK dependency)."""

    def __init__(self, api_key: str, model: str, timeout: float = 300.0, base_url: str = "https://api.openai.com"):
        self.name = f"openai:{model}"
        self.model = model
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout,
                                         headers={"Authorization": f"Bearer {api_key}"})

    @property
    def _reasoning(self) -> bool:
        # reasoning-family models take max_completion_tokens and no temperature
        return self.model.startswith(("o1", "o3", "o4", "gpt-5", "gpt-6"))

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
        body: dict = {"model": self.model, "messages": messages}
        if self._reasoning:
            body["max_completion_tokens"] = max(max_tokens, 4000)
        else:
            body["max_tokens"] = max_tokens
            body["temperature"] = temperature
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            resp = await self._client.post("/v1/chat/completions", json=body)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise LLMError(f"openai request failed: {e.response.status_code} {e.response.text[:300]}") from e
        except httpx.HTTPError as e:
            raise LLMError(f"openai request failed: {e}") from e
        return resp.json()["choices"][0]["message"]["content"] or ""

    async def aclose(self) -> None:
        await self._client.aclose()
