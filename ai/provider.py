"""Provider accessor. OpenRouter is the single LLM provider.

Kept as a thin factory so callers (graph, crons, functions) import one place.
OpenRouterProvider handles its own retries and an optional OPENROUTER_FALLBACK_MODEL.
"""
from .base import AIProvider
from .openrouter_provider import OpenRouterProvider


def get_provider() -> AIProvider:
    return OpenRouterProvider()
