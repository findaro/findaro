from __future__ import annotations

import json
import re
from typing import Any, Protocol


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    name: str

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str: ...


def parse_json(text: str) -> Any:
    """Parse JSON from an LLM reply, tolerating code fences and leading/trailing prose."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start, end = text.find(open_ch), text.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError(f"could not parse JSON from LLM output: {text[:200]!r}")


def get_llm(provider: str | None = None, model: str | None = None) -> LLM:
    from zerch.config import get_settings

    settings = get_settings()
    provider = provider or settings.llm_provider
    if provider == "ollama":
        from zerch.llm.ollama import OllamaLLM

        return OllamaLLM(base_url=settings.ollama_url, model=model or settings.ollama_model)
    if provider == "anthropic":
        from zerch.llm.anthropic import AnthropicLLM

        if not settings.anthropic_api_key:
            raise LLMError("ZERCH_ANTHROPIC_API_KEY is not set")
        return AnthropicLLM(api_key=settings.anthropic_api_key, model=model or settings.anthropic_model)
    if provider == "openai":
        from zerch.llm.openai import OpenAILLM

        if not settings.openai_api_key:
            raise LLMError("OPENAI_API_KEY is not set")
        return OpenAILLM(api_key=settings.openai_api_key, model=model or settings.openai_model)
    raise LLMError(f"unknown LLM provider {provider!r}")
