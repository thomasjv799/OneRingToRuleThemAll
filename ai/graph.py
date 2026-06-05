"""LangGraph agent: load_memory → agent → execute_tools → save_memory."""
import json
from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

import db.client as db
from ai.openrouter_provider import OpenRouterProvider
from bot.functions import TOOLS, dispatch

_llm = OpenRouterProvider()

SYSTEM_PROMPT = (
    "You are OneRing, a homelab assistant. "
    "You can query and update vehicle documents (insurance, pollution, fitness, tax, permit), "
    "and check the user's tracked games and watches. "
    "Be concise and helpful."
)


class State(TypedDict):
    user_id: str
    messages: Annotated[list, add_messages]


def _load_memory(state: State) -> dict:
    uid = state["user_id"]
    summary = db.get_summary(uid)
    history = db.get_chat_history(uid, limit=10)
    system = SYSTEM_PROMPT
    if summary:
        system += f"\n\nConversation summary so far:\n{summary}"
    return {"messages": [{"role": "system", "content": system}] + history}


def _agent(state: State) -> dict:
    reply = _llm.chat(state["messages"], tools=TOOLS)
    return {"messages": [reply]}


def _should_call_tools(state: State) -> str:
    last = state["messages"][-1]
    if isinstance(last, dict) and last.get("tool_calls"):
        return "execute_tools"
    return "save_memory"


def _execute_tools(state: State) -> dict:
    uid = state["user_id"]
    last = state["messages"][-1]
    results = []
    for tc in last["tool_calls"]:
        args = json.loads(tc["function"]["arguments"])
        result = dispatch(tc["function"]["name"], args, uid)
        results.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": result,
        })
    return {"messages": results}


def _save_memory(state: State) -> dict:
    uid = state["user_id"]
    for msg in state["messages"]:
        if isinstance(msg, dict) and msg.get("role") in ("user", "assistant"):
            content = msg.get("content") or ""
            if content:
                db.save_message(uid, msg["role"], content)
    return {}


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


def run_graph(user_id: str, text: str) -> str:
    result = graph.invoke({"user_id": user_id, "messages": [{"role": "user", "content": text}]})
    last = result["messages"][-1]
    return last.get("content") or ""
