from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from findaro.llm.base import LLMError


class OpenAILLM:
    """Minimal Chat Completions client (no SDK dependency)."""

    def __init__(self, api_key: str, model: str, timeout: float = 300.0, base_url: str = "https://api.openai.com",
                 reasoning_effort: str | None = None):
        self.name = f"openai:{model}"
        self.model = model
        self.reasoning_effort = reasoning_effort
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout,
                                         headers={"Authorization": f"Bearer {api_key}"})

    @property
    def _reasoning(self) -> bool:
        # reasoning-family models take max_completion_tokens and no temperature
        return self.model.startswith(("o1", "o3", "o4", "gpt-5", "gpt-6"))

    def _body(self, prompt: str, system: str | None, temperature: float, max_tokens: int, json_mode: bool,
              messages: list[dict] | None = None) -> dict:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages or [{"role": "user", "content": prompt}])
        body: dict = {"model": self.model, "messages": msgs}
        if self._reasoning:
            body["max_completion_tokens"] = max(max_tokens, 4000) if not self.reasoning_effort else max_tokens * 4
            if self.reasoning_effort:
                body["reasoning_effort"] = self.reasoning_effort
        else:
            body["max_tokens"] = max_tokens
            body["temperature"] = temperature
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        json_mode: bool = False,
        messages: list[dict] | None = None,
    ) -> str:
        body = self._body(prompt, system, temperature, max_tokens, json_mode, messages)
        try:
            resp = await self._client.post("/v1/chat/completions", json=body)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise LLMError(f"openai request failed: {e.response.status_code} {e.response.text[:300]}") from e
        except httpx.HTTPError as e:
            raise LLMError(f"openai request failed: {e}") from e
        return resp.json()["choices"][0]["message"]["content"] or ""

    async def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 400,
        messages: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        body = self._body(prompt, system, temperature, max_tokens, False, messages)
        body["stream"] = True
        try:
            async with self._client.stream("POST", "/v1/chat/completions", json=body) as resp:
                if resp.status_code >= 400:
                    text = (await resp.aread()).decode(errors="replace")
                    raise LLMError(f"openai stream failed: {resp.status_code} {text[:300]}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    choices = json.loads(data).get("choices") or []
                    delta = (choices[0].get("delta") or {}).get("content") if choices else None
                    if delta:
                        yield delta
        except httpx.HTTPError as e:
            raise LLMError(f"openai stream failed: {e}") from e

    async def aclose(self) -> None:
        await self._client.aclose()
