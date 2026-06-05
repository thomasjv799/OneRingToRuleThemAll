from abc import ABC, abstractmethod


class AIProvider(ABC):
    @abstractmethod
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """Return an OpenAI-format assistant message dict (role/content/tool_calls)."""
        ...

    def generate_text(self, prompt: str) -> str:
        """Single-shot text completion. Used by cron jobs for buy commentary / summaries."""
        reply = self.chat([{"role": "user", "content": prompt}], tools=None)
        return reply.get("content") or ""
