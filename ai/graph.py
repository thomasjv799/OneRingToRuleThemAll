"""LangGraph agent: load_memory → agent → execute_tools → save_memory."""
import json
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
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

_ROLE_MAP = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}


def _to_dict(msg) -> dict:
    """Convert LangChain message objects to plain OpenAI-format dicts."""
    if not isinstance(msg, BaseMessage):
        return msg
    d = {"role": _ROLE_MAP.get(msg.type, msg.type), "content": msg.content or ""}
    if msg.type == "ai":
        tool_calls = msg.additional_kwargs.get("tool_calls")
        if tool_calls:
            d["tool_calls"] = tool_calls
    if msg.type == "tool":
        d["tool_call_id"] = getattr(msg, "tool_call_id", "")
    return d


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
    reply = _llm.chat([_to_dict(m) for m in state["messages"]], tools=TOOLS)
    return {"messages": [reply]}


def _should_call_tools(state: State) -> str:
    last = state["messages"][-1]
    if isinstance(last, BaseMessage):
        if last.additional_kwargs.get("tool_calls"):
            return "execute_tools"
    elif isinstance(last, dict) and last.get("tool_calls"):
        return "execute_tools"
    return "save_memory"


def _execute_tools(state: State) -> dict:
    uid = state["user_id"]
    last = state["messages"][-1]
    tool_calls = (
        last.additional_kwargs.get("tool_calls", [])
        if isinstance(last, BaseMessage)
        else last.get("tool_calls", [])
    )
    results = []
    for tc in tool_calls:
        args = json.loads(tc["function"]["arguments"])
        result = dispatch(tc["function"]["name"], args, uid)
        results.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
    return {"messages": results}


def _save_memory(state: State) -> dict:
    uid = state["user_id"]
    for msg in state["messages"]:
        if isinstance(msg, BaseMessage):
            role = _ROLE_MAP.get(msg.type)
            content = msg.content or ""
        elif isinstance(msg, dict):
            role = msg.get("role")
            content = msg.get("content") or ""
        else:
            continue
        if role in ("user", "assistant") and content:
            db.save_message(uid, role, content)
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


def run_graph(user_id: str, text: str) -> str:
    result = graph.invoke({"user_id": user_id, "messages": [{"role": "user", "content": text}]})
    last = result["messages"][-1]
    if isinstance(last, BaseMessage):
        return last.content or ""
    return last.get("content") or ""
