"""A small LangGraph agent: the model calls tools until it has an answer.

Spelled out as a StateGraph instead of a prebuilt helper on purpose: this is
the starting point to copy when a project needs its own graph (extra nodes,
human approval before CAD writes, several cooperating agents, ...).

    model --(tool calls?)--> tools --> model --> ... --> END
"""

import json

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.ai.client import AiError

#: Model turns per run before LangGraph stops the loop
RECURSION_LIMIT = 25


def react_agent(model, tools, prompt=None):
    """Compiled graph over ``MessagesState``; ``model`` is any LangChain chat model."""
    tools = list(tools)
    llm = model.bind_tools(tools) if tools else model
    system = [SystemMessage(prompt)] if prompt else []

    async def call_model(state):
        return {"messages": [await llm.ainvoke(system + state["messages"])]}

    graph = StateGraph(MessagesState)
    graph.add_node("model", call_model)
    graph.add_edge(START, "model")
    if tools:
        graph.add_node("tools", ToolNode(tools))
        graph.add_conditional_edges("model", tools_condition, {"tools": "tools", END: END})
        graph.add_edge("tools", "model")
    else:
        graph.add_edge("model", END)
    return graph.compile()


async def run(agent, message, model=None):
    """One question -> ``{"model", "answer", "steps"}``; Ollama errors become AiError."""
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
    return {"model": model, "answer": _text(messages[-1]), "steps": _steps(messages)}


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
