import os
import httpx
from dotenv import load_dotenv
from .base import AIProvider

load_dotenv()

_BASE = "https://openrouter.ai/api/v1"


class OpenRouterProvider(AIProvider):
    def __init__(self):
        self.api_key = os.environ["OPENROUTER_API_KEY"]
        self.model = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        payload = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
        resp = httpx.post(
            f"{_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]
