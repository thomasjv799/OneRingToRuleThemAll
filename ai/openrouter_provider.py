import logging
import os
import time

import httpx
from dotenv import load_dotenv
from langfuse import get_client

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

    def _record_usage(self, data: dict, requested_model: str) -> None:
        """Push model + token usage + OpenRouter's actual cost onto the active
        Langfuse generation. OpenRouter is the source of truth for cost, so we
        forward usage.cost directly instead of relying on Langfuse's price table
        (which never matches OpenRouter's `provider/model` naming)."""
        usage = data.get("usage") or {}
        try:
            get_client().update_current_generation(
                model=data.get("model", requested_model),
                usage_details={
                    "input": usage.get("prompt_tokens"),
                    "output": usage.get("completion_tokens"),
                    "total": usage.get("total_tokens"),
                },
                cost_details=(
                    {"total": usage["cost"]} if usage.get("cost") is not None else None
                ),
            )
        except Exception as exc:  # never let tracing break the bot
            log.debug("Langfuse usage update failed: %s", exc)

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        # include.usage → OpenRouter returns token counts and the actual cost charged.
        payload = {"messages": messages, "usage": {"include": True}}
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
                    data = resp.json()
                    self._record_usage(data, model)
                    return data["choices"][0]["message"]
                time.sleep(2 ** attempt)
            log.warning("Model %s exhausted retries (last %s); trying next", model, resp.status_code)

        # All models/retries exhausted — raise the last error.
        last_resp.raise_for_status()
        return last_resp.json()["choices"][0]["message"]
