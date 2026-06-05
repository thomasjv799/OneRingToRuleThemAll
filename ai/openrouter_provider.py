import logging
import os
import time

import httpx
from dotenv import load_dotenv

from .base import AIProvider

load_dotenv()

log = logging.getLogger(__name__)

_BASE = "https://openrouter.ai/api/v1"
_RETRIES = 3
_RETRY_CODES = {429, 500, 502, 503}


class OpenRouterProvider(AIProvider):
    def __init__(self):
        self.api_key = os.environ["OPENROUTER_API_KEY"]
        # Primary (free) model, then paid fallback when the free tier is rate-limited.
        self.model = os.environ.get("OPENROUTER_MODEL", "moonshotai/kimi-k2.6:free")
        self.fallback_model = os.environ.get(
            "OPENROUTER_FALLBACK_MODEL", "deepseek/deepseek-chat-v3-0324"
        )

    def _post(self, model: str, payload: dict) -> httpx.Response:
        return httpx.post(
            f"{_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={**payload, "model": model},
            timeout=60,
        )

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        payload = {"messages": messages}
        if tools:
            payload["tools"] = tools

        models = [self.model]
        if self.fallback_model and self.fallback_model != self.model:
            models.append(self.fallback_model)

        last_resp = None
        for model in models:
            for attempt in range(_RETRIES):
                resp = self._post(model, payload)
                last_resp = resp
                if resp.status_code not in _RETRY_CODES:
                    resp.raise_for_status()
                    return resp.json()["choices"][0]["message"]
                time.sleep(2 ** attempt)
            log.warning("Model %s exhausted retries (last %s); trying next", model, resp.status_code)

        # All models/retries exhausted — raise the last error.
        last_resp.raise_for_status()
        return last_resp.json()["choices"][0]["message"]
