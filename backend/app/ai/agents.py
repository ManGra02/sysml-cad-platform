"""A small LangGraph agent: the model calls tools until it has an answer.

Spelled out as a StateGraph instead of a prebuilt helper on purpose: this is
the starting point to copy when a project needs its own graph (extra nodes,
human approval before CAD writes, several cooperating agents, ...).

    model --(tool calls?)--> tools --> model --> ... --> [respond] --> END

``respond`` only exists with ``response_format``: it turns the conversation into
a structured result (a Pydantic model), returned by run() as ``result``.
"""

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.ai.client import AiError

#: Model turns per run before LangGraph stops the loop
RECURSION_LIMIT = 25

#: Last instruction before the structured result is produced
RESPOND = "Now give the final result in the requested structure, based only on the conversation above."


class AgentState(MessagesState):
    structured_response: Any


def react_agent(model, tools, prompt=None, response_format=None):
    """Compiled graph over ``AgentState``; ``model`` is any LangChain chat model.

    ``response_format``: a Pydantic model class -- after the tool loop the model
    fills it in (``state["structured_response"]``)."""
    tools = list(tools)
    llm = model.bind_tools(tools) if tools else model
    system = [SystemMessage(prompt)] if prompt else []
    finish = "respond" if response_format is not None else END

    async def call_model(state):
        return {"messages": [await llm.ainvoke(system + state["messages"])]}

    async def respond(state):
        structured = model.with_structured_output(response_format)
        return {"structured_response": await structured.ainvoke(
            system + state["messages"] + [HumanMessage(RESPOND)])}

    graph = StateGraph(AgentState)
    graph.add_node("model", call_model)
    graph.add_edge(START, "model")
    if tools:
        graph.add_node("tools", ToolNode(tools))
        graph.add_conditional_edges("model", tools_condition, {"tools": "tools", END: finish})
        graph.add_edge("tools", "model")
    else:
        graph.add_edge("model", finish)
    if response_format is not None:
        graph.add_node("respond", respond)
        graph.add_edge("respond", END)
    return graph.compile()


async def run(agent, message, model=None):
    """One question -> ``{"model", "answer", "steps"}`` (+ ``result`` with a response_format);
    Ollama errors become AiError."""
    try:
        state = await agent.ainvoke({"messages": [("user", message)]},
                                    {"recursion_limit": RECURSION_LIMIT})
    except AiError:
        raise
    except Exception as exc:   # ollama.ResponseError, httpx errors, GraphRecursionError ...
        status = getattr(exc, "status_code", None)
        if status in (401, 403):
            raise AiError(502, "ai_unauthorized", "Ollama rejected the API key (check OLLAMA_API_KEY)") from exc
        if status == 404:
            raise AiError(502, "ai_model_not_found", "Ollama does not know the model: %s" % exc) from exc
        raise AiError(502, "ai_agent_failed", "Agent run failed: %s" % exc,
                      {"type": type(exc).__name__}) from exc
    messages = state["messages"]
    out = {"model": model, "answer": _text(messages[-1]), "steps": _steps(messages)}
    structured = state.get("structured_response")
    if structured is not None:
        out["result"] = structured.model_dump() if hasattr(structured, "model_dump") else structured
    return out


def _text(message):
    content = message.content
    if isinstance(content, list):   # content blocks
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return content


def _steps(messages):
    """Which tools were called with what -- for the UI and for tracing results."""
    steps = []
    for m in messages:
        if isinstance(m, AIMessage):
            steps += [{"tool": c["name"], "args": c["args"], "id": c["id"]} for c in m.tool_calls]
        elif isinstance(m, ToolMessage):
            for step in steps:
                if step.get("id") == m.tool_call_id:
                    step["result"] = _text(m)[:500]
    for step in steps:
        step.pop("id", None)
    return json.loads(json.dumps(steps, default=str))
