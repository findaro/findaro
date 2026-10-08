"""LLM provider interface.

Used by the query planner (only for queries the rules can't read, behind a timeout), chat answers, and scripts.
Providers: Ollama (default, local), OpenAI and Anthropic (paid, opt-in via ZERCH_CHAT_PROVIDER /
ZERCH_PLANNER_PROVIDER).
"""

from zerch.llm.base import LLM, LLMError, get_llm

__all__ = ["LLM", "LLMError", "get_llm"]
