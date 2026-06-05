"""LangGraph agent: load_memory → agent → execute_tools → save_memory.

Messages are plain OpenAI-format dicts throughout (role/content/tool_calls),
which is exactly what the OpenRouter API speaks — no LangChain message objects.
"""
import json
import logging
import operator
import os
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from langfuse import Langfuse, observe
from langgraph.graph import END, StateGraph

import db.client as db
from ai.provider import get_provider
from bot.functions import TOOLS, dispatch

# --- Langfuse initialization (must happen before @observe is used) ---
load_dotenv()
_langfuse = Langfuse(
    secret_key=os.environ.get("LANGFUSE_SECRET_KEY"),
    public_key=os.environ.get("LANGFUSE_PUBLIC_KEY"),
    host=os.environ.get("LANGFUSE_HOST", "https://us.cloud.langfuse.com"),
)

log = logging.getLogger(__name__)

_llm = get_provider()

SYSTEM_PROMPT = (
    "You are OneRing, a homelab assistant. You can:\n"
    "- Query and update vehicle documents (insurance, PUCC/pollution, fitness, MV tax, permit) "
    "and snooze their renewal reminders.\n"
    "- Track game prices: add/remove games, set target prices, look up current and historical-low "
    "prices, and show recent deal alerts.\n"
    "- Track watch prices from swisstimehouse.com links: add/remove watches, set targets, "
    "and check current prices.\n"
    "- Monitor the home server: current health (CPU/RAM/disk/temp), metric trends "
    "over time, Docker container status and health, and container logs. Prefer the "
    "named helpers (get_system_health, get_metric_range, get_container_status, "
    "search_logs); use query_prometheus/query_loki only for unusual questions.\n"
    "- Report OpenRouter cost: current balance and spend over a date range "
    "(get_openrouter_balance, get_openrouter_usage).\n"
    "When updating a vehicle expiry, first show the user the old → new value and ask them to "
    "confirm before calling update_vehicle_expiry. Be concise and helpful."
)


class State(TypedDict):
    user_id: str
    user_text: str
    messages: Annotated[list, operator.add]


@observe()
def _load_memory(state: State) -> dict:
    uid = state["user_id"]
    summary = db.get_summary(uid)
    history = db.get_chat_history(uid, limit=10)
    system = SYSTEM_PROMPT
    if summary:
        system += f"\n\nConversation summary so far:\n{summary}"
    messages = (
        [{"role": "system", "content": system}]
        + history
        + [{"role": "user", "content": state["user_text"]}]
    )
    return {"messages": messages}


@observe(as_type="generation")
def _agent(state: State) -> dict:
    reply = _llm.chat(state["messages"], tools=TOOLS)
    return {"messages": [reply]}


def _should_call_tools(state: State) -> str:
    last = state["messages"][-1]
    if last.get("tool_calls"):
        return "execute_tools"
    return "save_memory"


@observe()
def _execute_tools(state: State) -> dict:
    uid = state["user_id"]
    results = []
    for tc in state["messages"][-1]["tool_calls"]:
        args = json.loads(tc["function"]["arguments"] or "{}")
        result = dispatch(tc["function"]["name"], args, uid)
        results.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
    return {"messages": results}


@observe()
def _save_memory(state: State) -> dict:
    """Persist only this turn: the incoming user message + the final assistant reply."""
    uid = state["user_id"]
    db.save_message(uid, "user", state["user_text"])
    for msg in reversed(state["messages"]):
        if msg.get("role") == "assistant" and msg.get("content"):
            db.save_message(uid, "assistant", msg["content"])
            break
    return {"messages": []}


graph = (
    StateGraph(State)
    .add_node("load_memory", _load_memory)
    .add_node("agent", _agent)
    .add_node("execute_tools", _execute_tools)
    .add_node("save_memory", _save_memory)
    .set_entry_point("load_memory")
    .add_edge("load_memory", "agent")
    .add_conditional_edges("agent", _should_call_tools)
    .add_edge("execute_tools", "agent")
    .add_edge("save_memory", END)
    .compile()
)


@observe()
def run_graph(user_id: str, text: str) -> str:
    # Resolve platform-specific id (e.g. Telegram) to the canonical owner id so
    # tool lookups and chat memory are unified across platforms.
    user_id = db.resolve_user_id(user_id)
    try:
        result = graph.invoke({"user_id": user_id, "user_text": text, "messages": []})
        return result["messages"][-1].get("content") or ""
    finally:
        try:
            _langfuse.flush()
        except Exception as exc:  # never let tracing break the bot
            log.debug("Langfuse flush failed: %s", exc)
