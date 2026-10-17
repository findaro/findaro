"""LLM provider interface.

Used by the query planner (only for queries the rules can't read, behind a timeout), chat answers, and scripts.
Providers: Ollama (default, local), OpenAI and Anthropic (paid, opt-in via FINDARO_CHAT_PROVIDER /
FINDARO_PLANNER_PROVIDER).
"""

from findaro.llm.base import LLM, LLMError, get_llm

__all__ = ["LLM", "LLMError", "get_llm"]
