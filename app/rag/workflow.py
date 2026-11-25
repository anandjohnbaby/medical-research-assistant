from langgraph.graph import END, StateGraph

from app.core import safety_rules
from app.rag import nodes
from app.rag.state import GraphState


def _build():
    g = StateGraph(GraphState)
    g.add_node("safety", nodes.safety_node)
    g.add_node("router", nodes.router_node)
    g.add_node("direct", nodes.direct_node)
    g.add_node("understand", nodes.understand_node)
    g.add_node("retrieve", nodes.retrieve_node)
    g.add_node("grade", nodes.grade_node)
    g.add_node("web", nodes.web_node)
    g.add_node("rewrite", nodes.rewrite_node)
    g.add_node("generate", nodes.generate_node)
    g.add_node("verify", nodes.verify_node)
    g.add_node("correct", nodes.correct_node)
    g.add_node("finalize", nodes.finalize_node)
    g.add_node("insufficient", nodes.insufficient_node)

    g.set_entry_point("safety")
    g.add_conditional_edges("safety", lambda s: "end" if s.get("route") == "emergency" else "router",
                            {"end": END, "router": "router"})
    g.add_conditional_edges("router", lambda s: s["route"], {"direct": "direct", "medical": "understand"})
    g.add_edge("direct", END)
    g.add_edge("understand", "retrieve")
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", nodes.route_after_grade,
                            {"generate": "generate", "web": "web", "rewrite": "rewrite",
                             "insufficient": "insufficient"})
    g.add_edge("web", "grade")
    g.add_edge("rewrite", "understand")
    g.add_edge("generate", "verify")
    g.add_conditional_edges("verify", nodes.route_after_verify,
                            {"finalize": "finalize", "correct": "correct", "insufficient": "insufficient"})
    g.add_edge("correct", "verify")
    g.add_edge("finalize", END)
    g.add_edge("insufficient", END)
    return g.compile()


_graph = None


def run(question: str) -> dict:
    global _graph
    if _graph is None:
        _graph = _build()
    state = _graph.invoke(
        {"question": question, "evidence": [], "rewrite_count": 0, "correction_round": 0,
         "web_attempted": False, "verification_history": [], "trace": []},
        config={"recursion_limit": 40},
    )
    safety = state.get("safety", {})
    notice = safety_rules.PERSONAL_NOTICE if safety.get("personalized") and state.get("outcome") in ("answered", "insufficient") else ""
    citations = state.get("citations", [])
    return {
        "answer": state.get("final_answer", ""),
        "outcome": state.get("outcome", "direct"),
        "confidence": state.get("confidence", {"label": "N/A", "score": 0.0, "reasons": []}),
        "citations": citations,
        "claims": state.get("claims", []) if state.get("outcome") in ("answered", "insufficient") else [],
        "verification": state.get("verification_history", []),
        "conflicts": state.get("conflicts", []) if state.get("outcome") == "answered" else [],
        "considered": state.get("considered", []),
        "sources_used": sorted({c["source"] for c in citations}),
        "trace": state.get("trace", []),
        "safety": {"emergency": safety.get("emergency", False), "category": safety.get("category", ""),
                   "personal_notice": notice},
        "disclaimer": safety_rules.DISCLAIMER,
    }