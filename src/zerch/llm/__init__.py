"""LLM provider interface.

M1 uses this only from scripts (demo catalog generation). It is deliberately not imported by the
search hot path; M2 query understanding will build on it.
"""

from zerch.llm.base import LLM, LLMError, get_llm

__all__ = ["LLM", "LLMError", "get_llm"]
