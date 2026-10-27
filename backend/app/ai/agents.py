"""A small LangGraph agent: the model calls tools until it has an answer.

Spelled out as a StateGraph instead of a prebuilt helper on purpose: this is
the starting point to copy when a project needs its own graph (extra nodes,
human approval before CAD writes, several cooperating agents, ...).

    model --(tool calls?)--> tools --> model --> ... --> [respond] --> END

``respond`` only exists with ``response_format``: it turns the conversation into
a structured result (a Pydantic model), returned by run() as ``result`` -- or
``result: None`` plus ``resultError`` when the model does not deliver one.
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
#: Second attempt, for models that answer the first one in prose
RESPOND_JSON = ("Answer with ONLY one JSON object, no prose and no code fence, that matches this "
                "JSON schema:\n%s")


class AgentState(MessagesState):
    structured_response: Any
    structured_error: str | None


async def structured_result(model, schema, messages):
    """The conversation as an instance of ``schema`` -> (instance, None) or (None, why not).

    Ollama Cloud ignores ``format`` (the JSON schema LangChain sends by default),
    so the schema goes in as a tool the model has to call. Models that answer that
    in prose get a second chance with the schema in the prompt. Failing both is
    reported, not raised: the text answer of the run stays usable."""
    try:
        out = await model.with_structured_output(schema, method="function_calling", include_raw=True) \
            .ainvoke(messages + [HumanMessage(RESPOND)])
        if out.get("parsed") is not None:
            return out["parsed"], None
        first = "no tool call" if out.get("parsing_error") is None else str(out["parsing_error"])
    except Exception as exc:   # tool calling not supported, invalid arguments ...
        first = "%s: %s" % (type(exc).__name__, exc)
    reply = await model.ainvoke(messages + [HumanMessage(RESPOND_JSON % json.dumps(schema.model_json_schema()))])
    text = _text(reply)
    start, end = text.find("{"), text.rfind("}")
    try:
        return schema.model_validate_json(text[start:end + 1] if start >= 0 else text), None
    except ValueError as exc:
        return None, "model gave no valid %s (tool call: %s; JSON: %s)" % (
            schema.__name__, first[:200], str(exc).splitlines()[0][:200])


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
        messages = system + [HumanMessage(_transcript(state["messages"]))]
        result, error = await structured_result(model, response_format, messages)
        return {"structured_response": result, "structured_error": error}

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
    """One question -> ``{"model", "answer", "steps"}`` (+ ``result`` with a response_format,
    ``resultError`` if that failed); Ollama errors become AiError."""
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
    elif state.get("structured_error"):
        out["result"] = None
        out["resultError"] = state["structured_error"]
    return out


#: Characters of one tool result in the transcript for the structured step
TRANSCRIPT_RESULT = 4000


def _transcript(messages):
    """The run as plain text. Raw tool-call history makes models call those tools again
    instead of the schema tool, so the structured step gets this instead."""
    lines = []
    for m in messages:
        if isinstance(m, ToolMessage):
            lines.append("[result of %s]\n%s" % (m.name, _text(m)[:TRANSCRIPT_RESULT]))
        elif isinstance(m, AIMessage):
            lines += ["[called %s %s]" % (c["name"], json.dumps(c["args"], ensure_ascii=False))
                      for c in m.tool_calls]
            if _text(m):
                lines.append("[assistant]\n" + _text(m))
        else:
            lines.append("[user]\n" + _text(m))
    return "The work done so far:\n\n" + "\n\n".join(lines)


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
