"""The CRA agent -- an engineering agent that reuses parts and finds CAD models.

Missions (the engineer asks in plain words, nothing is typed into forms):
  A  a part the SysML model needs has no CAD  -> find an existing PLM part to reuse
  B  a PLM part has no CAD model attached      -> find a CAD model for it

Its own graph (copied from app.ai.agents and extended by a review step):

    agent --(tool calls)--> tools --> agent --> ... --> review --(issues)--> agent
                                                          \\--(approved)--> respond --> END

The agent plans and acts with the tools; a reviewer (second LLM call, different role)
checks the answer against the tool evidence before it reaches the engineer and sends
it back with concrete issues if needed. Guardrails (guardrails.py) hold in every step.
"""

from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import BaseModel, Field

from app.ai.tools import cad_tools, calc_tools, progress_tool, sysml_tools
from app.projects.cra.session import CraSession
from app.projects.cra.tools import cra_tools

#: How often the reviewer may send an answer back
MAX_REVIEWS = 2
#: Graph steps per run (one tool round = 2 steps); the platform default of 25 is too few for
#: understand -> search -> verify -> relax -> search again -> review
STEP_LIMIT = 100
#: Rejected by the supervisors -- the CRA agent does not use it
EXCLUDED_TOOLS = {"sysml_neighbours"}

PROMPT = """You are the CAD Reuse Assistant, an engineering agent working with a SysML v2 model, a FreeCAD
model and the PLM (Cascadia). Your missions:
A) A part the SysML model needs has no CAD -> find an existing PLM part to reuse.
B) A PLM part has no CAD model attached -> find a CAD model for it.
Work like a careful engineer, and decide the steps yourself:
1. Gather the facts about the part: SysML (sysml_find, sysml_attributes, sysml_requirements) or the PLM
   (plm_item). For "which parts are missing", compare sysml_parts(leaf_only) with cad_tree, or use
   plm_parts_without_cad.
2. Understand the part with understand_part before searching. Its rules say what must match. If it says
   the item needs no CAD model (a consumable, software, a service), say so instead of searching.
3. search_parts. For mission B use cad_required=true.
4. Never trust PLM data blindly: verify_part every part you want to recommend. Do not recommend a
   suspicious part without saying what is contradictory.
5. If nothing fits, think about whether a non-critical rule can be relaxed (relax_rule, with a reason)
   and search again. Critical rules stay. If still nothing fits, say so -- and for mission B offer
   propose_envelope_model as a placeholder.
Be efficient: call independent tools together in one turn, verify only the 2-3 best candidates, and do
not repeat a call that already answered. Only tool results count: never invent item numbers, values or
files. Use report_progress on longer tasks.
Answer briefly in the language of the question: what the part is, what you recommend and why, what you
checked, and what is uncertain."""

REVIEW = """You review an engineering agent's answer before it reaches the engineer. Check it against the
tool results in the conversation only:
- Did it understand the part (understand_part) before searching?
- Is every recommended part backed by a search result with status fits (or a clearly explained exception)?
- Was every recommended part verified (verify_part), and are contradictions reported?
- Were only non-critical rules relaxed, each with a reason?
- Are all item numbers, values and files taken from tool results, nothing invented?
- If nothing fits, does it say so clearly instead of forcing a match?
Approve if all hold. Otherwise list concrete issues the agent can fix with its tools."""

RESPOND = "Now give the final result in the requested structure, based only on the conversation above."


class Review(BaseModel):
    approved: bool
    issues: list[str] = Field(default_factory=list)


class CraResult(BaseModel):
    """The agent's decision, for the UI."""
    mission: Literal["reuse_part", "find_cad", "other"] = "other"
    subject: str = Field("", description="the part this is about (SysML name or PLM item number)")
    understanding: str = Field("", description="what the part is and what it does")
    outcome: Literal["reuse", "cad_found", "envelope_proposed", "nothing_suitable", "answer"] = "answer"
    item_number: str | None = Field(None, description="recommended PLM part, from tool results only")
    name: str | None = None
    cad_file: str | None = Field(None, description="CAD file of the recommended part, if any")
    confidence: Literal["high", "medium", "low"] = "low"
    evidence: list[str] = Field(default_factory=list, description="what was checked and passed")
    plm_issues: list[str] = Field(default_factory=list, description="contradictions found in PLM data")
    relaxed_rules: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class CraState(MessagesState):
    reviews: int
    review_notes: list
    structured_response: Any


def build_graph(model, tools, prompt=PROMPT):
    tools = list(tools)
    llm = model.bind_tools(tools) if tools else model
    system = [SystemMessage(prompt)]

    async def agent(state):
        return {"messages": [await llm.ainvoke(system + state["messages"])]}

    async def review(state):
        verdict = await model.with_structured_output(Review).ainvoke(
            [SystemMessage(REVIEW)] + _transcript(state["messages"]))
        if isinstance(verdict, dict):
            verdict = Review(**verdict)
        n = state.get("reviews", 0) + 1
        notes = list(state.get("review_notes") or []) + [verdict.model_dump()]
        if verdict.approved or n > MAX_REVIEWS:
            return {"reviews": n, "review_notes": notes}
        msg = HumanMessage("Reviewer: fix these issues with your tools, then answer again:\n- "
                           + "\n- ".join(verdict.issues or ["the answer is not backed by tool results"]))
        return {"reviews": n, "review_notes": notes, "messages": [msg]}

    def after_review(state):
        notes = state.get("review_notes") or []
        last = notes[-1] if notes else {"approved": True}
        return "respond" if last["approved"] or state.get("reviews", 0) > MAX_REVIEWS else "agent"

    async def respond(state):
        structured = model.with_structured_output(CraResult)
        result = await structured.ainvoke(system + state["messages"] + [HumanMessage(RESPOND)])
        return {"structured_response": result}

    graph = StateGraph(CraState)
    graph.add_node("agent", agent)
    graph.add_node("review", review)
    graph.add_node("respond", respond)
    graph.add_edge(START, "agent")
    if tools:
        graph.add_node("tools", ToolNode(tools))
        graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: "review"})
        graph.add_edge("tools", "agent")
    else:
        graph.add_edge("agent", "review")
    graph.add_conditional_edges("review", after_review, {"agent": "agent", "respond": "respond"})
    graph.add_edge("respond", END)
    return graph.compile()


def _transcript(messages):
    """The conversation as plain text for the reviewer (tool calls and results included)."""
    lines = []
    for m in messages:
        if isinstance(m, ToolMessage):
            lines.append("TOOL RESULT (%s): %s" % (m.name, str(m.content)[:3000]))
        elif getattr(m, "tool_calls", None):
            lines += ["AGENT CALLS %s %s" % (c["name"], c["args"]) for c in m.tool_calls]
        elif m.content:
            lines.append("%s: %s" % ("ENGINEER" if isinstance(m, HumanMessage) else "AGENT", m.content))
    return [HumanMessage("\n".join(lines))]


def agent_tools(ctx, session):
    tools = [t for t in sysml_tools(ctx) if t.name not in EXCLUDED_TOOLS]
    return tools + cad_tools(ctx) + cra_tools(session) + calc_tools() + [progress_tool(ctx)]


def build_agent(ctx, session=None):
    return build_graph(ctx.ai.chat_model(), agent_tools(ctx, session or CraSession(ctx)))
