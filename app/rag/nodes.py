import logging
import re
import threading

from app.rag import schemas
from app.core import safety_rules
from app.core.config import get_settings
from app.services import confidence, ingestion, llm, pubmed, vectorstore, web_search

log = logging.getLogger("medverify")
CITE = re.compile(r"\[(E\d+(?:\s*,\s*E\d+)*)\]")


# ----------------------------------------------------------------- helpers
def _merge(existing: list, new: list) -> list:
    seen, out = set(), []
    for e in list(existing) + list(new):
        key = e.get("key") or e.get("url") or e.get("title")
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    for i, e in enumerate(out, 1):
        e["id"] = f"E{i}"
    return out


def _ev_block(e: dict, limit: int = 1500) -> str:
    where = e.get("journal") or e.get("source")
    return f"[{e['id']}] ({e['study_type']}, {e['year'] or 'n.d.'}, {where}) {e['title']}\n{e['text'][:limit]}"


def _cites(text: str) -> list[str]:
    ids = []
    for m in CITE.finditer(text):
        for x in m.group(1).split(","):
            x = x.strip()
            if x not in ids:
                ids.append(x)
    return ids


def _tokens(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def quote_grounded(quote: str, source_text: str, threshold: float = 0.6) -> bool:
    """Deterministic anti-hallucination check: is the quoted excerpt really in the source?"""
    q = _tokens(quote)
    if not q:
        return False
    return len(q & _tokens(source_text)) / len(q) >= threshold


# ----------------------------------------------------------------- 1. safety
def safety_node(state):
    r = safety_rules.check(state["question"])
    if r["emergency"]:
        return {"route": "emergency", "outcome": "emergency", "final_answer": r["message"], "safety": r,
                "trace": [f"Safety gate -> EMERGENCY ({r['category']}); research answer withheld"]}
    note = " (personal-advice notice will be shown)" if r["personalized"] else ""
    return {"safety": r, "trace": [f"Safety gate -> clear{note}"]}


# ----------------------------------------------------------------- 2. router
ROUTER_SYS = (
    "Classify the user's message for a medical research assistant. "
    'Return {"route": "medical"} if it asks about health, disease, drugs, treatments, symptoms, '
    'nutrition, diagnostics or medical research. Return {"route": "direct"} for greetings, thanks, '
    "questions about the assistant, or anything non-medical."
)


def router_node(state):
    s = get_settings()
    out = llm.chat_json(ROUTER_SYS, state["question"], s.groq_fast_model, max_tokens=50,
                        schema=schemas.ROUTER, name="router")
    route = "medical" if out.get("route") == "medical" else "direct"
    return {"route": route, "trace": [f"Router -> {route.upper()}"]}


def direct_node(state):
    s = get_settings()
    text = llm.chat(
        "You are MedVerify AI, a medical research assistant that answers medical questions using "
        "published research with citations and claim verification. Reply in at most 3 short sentences. "
        "If the user's message is not a medical research question, politely say what you can help with "
        "and invite a medical question. Never give medical advice.",
        state["question"], s.groq_fast_model, temperature=0.3, max_tokens=200)
    return {"final_answer": text, "outcome": "direct", "trace": ["Direct answer (no retrieval needed)"]}


# ----------------------------------------------------------------- 3. query understanding
UNDERSTAND_SYS = (
    "Convert a medical question into search queries. Return JSON: "
    '{"pubmed_query": "...", "web_query": "..."}. '
    "pubmed_query: a concise PubMed query of 3-8 key medical terms joined with AND/OR (use synonyms "
    "with OR in parentheses). Do not use quotes or field tags. web_query: a short natural-language query."
)


def understand_node(state):
    s = get_settings()
    user = state["question"]
    if state.get("rewrite_count", 0) > 0:
        user += (f"\n\nThe previous query '{state.get('pubmed_query', '')}' returned weak evidence. "
                 "Rewrite with different synonyms, a broader or more specific angle.")
    out = llm.chat_json(UNDERSTAND_SYS, user, s.groq_fast_model, max_tokens=200,
                        schema=schemas.UNDERSTAND, name="queries")
    pq = out.get("pubmed_query") or state["question"]
    wq = out.get("web_query") or state["question"]
    return {"pubmed_query": pq, "web_query": wq, "trace": [f"Query understanding -> PubMed: {pq}"]}


# ----------------------------------------------------------------- 4. retrieval
def retrieve_node(state):
    s = get_settings()
    new, trace, articles = [], [], []
    try:
        kb = vectorstore.query_kb(state["question"], s.kb_top_k)
        new += kb
        trace.append(f"Knowledge base (Pinecone) -> {len(kb)} passages")
    except Exception as e:  # keep going with other sources
        log.warning("KB unavailable: %s", e)
        trace.append(f"Knowledge base unavailable ({type(e).__name__})")
    try:
        pmids = pubmed.search_pmids(state["pubmed_query"], s.pubmed_max)
        articles = pubmed.fetch_articles(pmids)
        live = [pubmed.to_evidence(a) for a in articles if not a["retracted"]]
        skipped = len(articles) - len(live)
        new += live
        trace.append(f"Live PubMed -> {len(live)} abstracts" + (f" ({skipped} retracted skipped)" if skipped else ""))
        if s.cache_pubmed_in_kb and articles:
            threading.Thread(target=_cache, args=(articles,), daemon=True).start()
    except Exception as e:
        log.warning("PubMed failed: %s", e)
        trace.append(f"PubMed unavailable ({type(e).__name__})")
    return {"evidence": _merge(state.get("evidence", []), new), "trace": trace}


def _cache(articles):
    try:
        vectorstore.upsert_chunks(ingestion.articles_to_chunks(articles))
    except Exception as e:
        log.info("KB cache skipped: %s", e)


# ----------------------------------------------------------------- 5. grading
GRADE_SYS = (
    "You grade sources for relevance to a medical question. For each source give relevance: "
    "2 = directly addresses the question, 1 = partially relevant or useful background, 0 = irrelevant. "
    'Return {"grades": [{"id": "E1", "relevance": 2}, ...]}.'
)


def grade_node(state):
    s = get_settings()
    ev = state.get("evidence", [])
    ungraded = [e for e in ev if "relevance" not in e]
    if ungraded:
        listing = "\n\n".join(f"[{e['id']}] {e['title']}\n{e['text'][:500]}" for e in ungraded)
        out = llm.chat_json(GRADE_SYS, f"QUESTION: {state['question']}\n\nSOURCES:\n{listing}",
                            s.groq_fast_model, max_tokens=600,
                            schema=schemas.GRADE, name="grades")
        rel = {}
        for g in out.get("grades", []):
            try:
                rel[str(g.get("id"))] = int(g.get("relevance", 0))
            except (TypeError, ValueError):
                pass
        for e in ungraded:
            e["relevance"] = max(0, min(2, rel.get(e["id"], 0)))

    relevant = [e for e in ev if e.get("relevance", 0) >= 1]
    relevant.sort(key=lambda e: (-e["relevance"], e["tier"], -e.get("score", 0)))
    relevant = relevant[:s.max_evidence]
    strong = [e for e in relevant if e["relevance"] == 2]
    good = len(relevant) >= 2 and len(strong) >= 1 and any(e["tier"] <= 4 for e in relevant)
    stage = "Web" if state.get("web_attempted") else "Evidence"
    return {"evidence": _merge(relevant, []), "grade": "good" if good else "weak",
            "trace": [f"{stage} grade -> {'GOOD' if good else 'WEAK'} "
                      f"({len(relevant)} relevant, {len(strong)} direct)"]}


def route_after_grade(state) -> str:
    if state["grade"] == "good":
        return "generate"
    if not state.get("web_attempted"):
        return "web"
    if state.get("rewrite_count", 0) < get_settings().max_rewrites:
        return "rewrite"
    return "insufficient"


def web_node(state):
    try:
        results = web_search.search(state.get("web_query") or state["question"])
        note = f"Trusted-domain web search (Tavily) -> {len(results)} results"
    except Exception as e:
        results, note = [], f"Web search unavailable ({type(e).__name__})"
    return {"evidence": _merge(state.get("evidence", []), results), "web_attempted": True, "trace": [note]}


def rewrite_node(state):
    n = state.get("rewrite_count", 0) + 1
    return {"rewrite_count": n, "web_attempted": False, "trace": [f"Evidence weak -> rewriting query (attempt {n})"]}


# ----------------------------------------------------------------- 7. generation
GENERATE_SYS = """You are MedVerify AI, a medical research assistant. Answer ONLY from the numbered evidence provided.
Rules:
1. Every factual sentence must contain citation tags such as [E1] or [E1][E3], placed BEFORE the final period, with no spaces between tags. Use only IDs that exist.
2. Never add facts, numbers, doses or recommendations that are not stated in the evidence.
3. If sources disagree, say so explicitly and cite both.
4. Mention the study type when it matters (for example "a meta-analysis found ...").
5. Do not give personal medical advice, diagnoses or individual dosing. Describe what the research shows.
6. If the evidence only partly answers the question, say what is not covered.
Format (plain text, no markdown symbols, no tables):
Summary: one or two sentences.
Key findings:
- one finding per line
Limitations: one or two short sentences about the strength or gaps of the evidence."""


def generate_node(state):
    s = get_settings()
    ev = "\n\n".join(_ev_block(e) for e in state["evidence"])
    answer = llm.chat(GENERATE_SYS, f"QUESTION: {state['question']}\n\nEVIDENCE:\n{ev}",
                      s.groq_strong_model, max_tokens=1200)
    return {"answer": answer, "correction_round": state.get("correction_round", 0),
            "trace": [f"Answer generated from {len(state['evidence'])} sources"]}


# ----------------------------------------------------------------- 8. claim verification
VERIFY_SYS = """You are a strict medical fact-checker. For each claim decide using ONLY the cited evidence provided.
SUPPORTED: the evidence explicitly states the claim or directly implies it, including numbers and direction of effect.
CONTRADICTED: the evidence states the opposite, or conflicting numbers or direction.
UNSUPPORTED: the evidence does not state it, covers it only partly, overgeneralises (wrong population, stronger certainty than the evidence), or adds details not in the evidence.
Return {"results": [{"id": "C1", "verdict": "SUPPORTED|UNSUPPORTED|CONTRADICTED", "quote": "verbatim excerpt (max 30 words) from the evidence that supports or contradicts the claim, empty if none", "reason": "one short sentence"}]}"""

CONFLICT_SYS = (
    "You compare medical sources for disagreement. Using only the excerpts, list pairs of sources whose "
    "findings about the question meaningfully conflict (opposite direction of effect, or clearly "
    'inconsistent results). Return {"conflicts": [{"ids": ["E1", "E2"], "description": "one sentence"}]}. '
    'Return {"conflicts": []} if there is no real disagreement.'
)


def split_claims(answer: str) -> list[dict]:
    text = re.sub(r"\]\s+(?=\[E\d)", "]", answer)
    text = re.sub(r"\.\s*((?:\[E\d+\])+)", lambda m: " " + m.group(1) + ".", text)
    claims, section = [], ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^(summary|key findings|limitations)\s*:\s*(.*)$", line, re.I)
        if m:
            section, line = m.group(1).lower(), m.group(2).strip()
            if not line:
                continue
        if section == "limitations":
            continue
        line = re.sub(r"^[-\u2022*]\s*", "", line)
        for sent in re.split(r"(?<=[.!?])\s+(?=[A-Z])", line):
            sent = sent.strip()
            if len(sent) < 15:
                continue
            clean = re.sub(r"\s+([.,;])", r"\1", CITE.sub("", sent)).strip()
            claims.append({"id": f"C{len(claims) + 1}", "text": clean, "raw": sent, "cited": _cites(sent)})
    return claims


def _verify_claims(claims: list[dict], ev: dict) -> None:
    s = get_settings()
    checkable = []
    for c in claims:
        c["valid_cited"] = [i for i in c["cited"] if i in ev]
        c.update(verdict="UNSUPPORTED", reason="", quote="")
        if not c["valid_cited"]:
            c["reason"] = "No valid citation provided for this statement."
        else:
            checkable.append(c)

    for i in range(0, len(checkable), 8):
        batch = checkable[i:i + 8]
        used = sorted({x for c in batch for x in c["valid_cited"]}, key=lambda k: int(k[1:]))
        payload = ("EVIDENCE:\n" + "\n\n".join(_ev_block(ev[k], 1800) for k in used) +
                   "\n\nCLAIMS:\n" + "\n".join(f"{c['id']}: {c['text']} (cites {', '.join(c['valid_cited'])})"
                                               for c in batch))
        out = llm.chat_json(VERIFY_SYS, payload, s.groq_strong_model, max_tokens=1800,
                            schema=schemas.VERIFY, name="verdicts")
        by_id = {str(r.get("id")): r for r in out.get("results", [])}
        for c in batch:
            r = by_id.get(c["id"])
            if not r:
                c["reason"] = "Verifier returned no verdict."
                continue
            verdict = str(r.get("verdict", "")).upper()
            c["verdict"] = verdict if verdict in ("SUPPORTED", "UNSUPPORTED", "CONTRADICTED") else "UNSUPPORTED"
            c["quote"] = str(r.get("quote", ""))[:300]
            c["reason"] = str(r.get("reason", ""))[:300]
            if c["verdict"] == "SUPPORTED":
                source = " ".join(ev[k]["title"] + " " + ev[k]["text"] for k in c["valid_cited"])
                if not c["quote"] or not quote_grounded(c["quote"], source):
                    c["verdict"] = "UNSUPPORTED"
                    c["reason"] = "Could not locate a matching excerpt in the cited source."


def verify_node(state):
    s = get_settings()
    ev = {e["id"]: e for e in state["evidence"]}
    claims = split_claims(state["answer"])
    _verify_claims(claims, ev)

    counts = {v: sum(1 for c in claims if c["verdict"] == v) for v in ("SUPPORTED", "UNSUPPORTED", "CONTRADICTED")}
    hist = {"round": state.get("correction_round", 0), "total": len(claims),
            "supported": counts["SUPPORTED"], "unsupported": counts["UNSUPPORTED"],
            "contradicted": counts["CONTRADICTED"]}

    conflicts = state.get("conflicts")
    if conflicts is None:
        conflicts = []
        used = sorted({i for c in claims for i in c["valid_cited"]}, key=lambda k: int(k[1:]))
        if len(used) >= 2:
            snippet = "\n\n".join(_ev_block(ev[k], 700) for k in used)
            out = llm.chat_json(CONFLICT_SYS, f"QUESTION: {state['question']}\n\nEXCERPTS:\n{snippet}",
                                s.groq_fast_model, max_tokens=500,
                                schema=schemas.CONFLICTS, name="conflicts")
            for c in out.get("conflicts", []):
                ids = [i for i in c.get("ids", []) if i in ev]
                if len(ids) >= 2:
                    conflicts.append({"ids": ids, "description": str(c.get("description", ""))[:300]})

    return {"claims": claims, "conflicts": conflicts, "verification_history": [hist],
            "trace": [f"Claim verification (round {hist['round']}) -> {counts['SUPPORTED']}/{len(claims)} supported, "
                      f"{counts['UNSUPPORTED']} unsupported, {counts['CONTRADICTED']} contradicted"]}


def route_after_verify(state) -> str:
    claims = state["claims"]
    if not claims:
        return "insufficient"
    if all(c["verdict"] == "SUPPORTED" for c in claims):
        return "finalize"
    if state.get("correction_round", 0) < get_settings().max_corrections:
        return "correct"
    return "finalize"


# ----------------------------------------------------------------- 9. correction
CORRECT_SYS = """You correct a draft medical answer so that every statement is supported by the evidence.
You receive the question, the evidence, the draft and a list of failed claims with reasons.
- Rewrite or delete each failed claim so it matches the evidence exactly; delete it if the evidence cannot support it.
- Keep supported claims unchanged. Keep the same format (Summary / Key findings / Limitations) and citation tags like [E1] placed before the final period.
- Do not add any new fact that is not in the evidence."""


def correct_node(state):
    s = get_settings()
    failed = "\n".join(f"- {c['text']} -> {c['verdict']}: {c['reason']}"
                       for c in state["claims"] if c["verdict"] != "SUPPORTED")
    ev = "\n\n".join(_ev_block(e) for e in state["evidence"])
    answer = llm.chat(
        CORRECT_SYS,
        f"QUESTION: {state['question']}\n\nEVIDENCE:\n{ev}\n\nDRAFT:\n{state['answer']}\n\nFAILED CLAIMS:\n{failed}",
        s.groq_strong_model, max_tokens=1200)
    n = state.get("correction_round", 0) + 1
    return {"answer": answer, "correction_round": n, "trace": [f"Corrector -> rewrote answer (round {n})"]}


# ----------------------------------------------------------------- 10/11. finalize
NOT_FOUND = ("I could not find enough reliable evidence in trusted medical sources to answer this question "
             "safely. Try rephrasing with more specific medical terms (condition, treatment, population), "
             "or consult a healthcare professional.")


def insufficient_node(state):
    considered = [{"title": e["title"], "url": e["url"], "year": e["year"], "study_type": e["study_type"]}
                  for e in state.get("evidence", [])[:5]]
    return {"final_answer": NOT_FOUND, "outcome": "insufficient", "claims": state.get("claims", []),
            "citations": [], "confidence": {"label": "Insufficient", "score": 0.0,
                                            "reasons": ["Evidence was too weak or could not be verified."]},
            "trace": ["Insufficient evidence -> returning a transparent refusal"],
            "considered": considered}


def finalize_node(state):
    s = get_settings()
    ev = {e["id"]: e for e in state["evidence"]}
    claims = state["claims"]
    good = [c for c in claims if c["verdict"] == "SUPPORTED"]
    bad = [c for c in claims if c["verdict"] != "SUPPORTED"]
    if not good:
        return insufficient_node(state)

    if bad:  # rebuild strictly from verified statements
        answer = "Verified findings:\n" + "\n".join(f"- {c['raw']}" for c in good)
        answer += (f"\n\nNote: {len(bad)} statement(s) in the draft answer were removed because they could "
                   "not be verified against the sources.")
    else:
        answer = state["answer"]
    answer = re.sub(r"\]\s+(?=\[E\d)", "]", answer)

    # sequential citation numbers in order of appearance
    order = {}
    for cid in _cites(answer):
        if cid in ev and cid not in order:
            order[cid] = len(order) + 1

    def repl(m):
        ids = [x.strip() for x in m.group(1).split(",")]
        return "".join(f"[{order[i]}]" for i in ids if i in order)

    answer = CITE.sub(repl, answer)

    conflicts = state.get("conflicts", [])
    if conflicts and not re.search(r"disagree|conflict|inconsisten|mixed|contradict", answer, re.I):
        answer += "\n\nNote: the sources do not fully agree. " + " ".join(
            f"{c['description']} (see [{']['.join(str(order[i]) for i in c['ids'] if i in order)}])"
            for c in conflicts if any(i in order for i in c["ids"]))

    year_now = __import__("datetime").date.today().year
    citations = []
    for eid, n in sorted(order.items(), key=lambda kv: kv[1]):
        e = ev[eid]
        citations.append({
            "n": n, "title": e["title"], "journal": e["journal"], "year": e["year"],
            "study_type": e["study_type"], "tier": e["tier"], "pmid": e["pmid"], "doi": e["doi"],
            "url": e["url"], "source": {"kb": "Knowledge base", "pubmed": "Live PubMed", "web": "Trusted web"}[e["source"]],
            "snippet": e["text"][:600],
            "old": bool(e["year"] and year_now - e["year"] > s.old_evidence_years),
        })

    cited_ev = [ev[i] for i in order]
    ui_claims = [{"id": c["id"], "text": c["text"], "verdict": c["verdict"], "reason": c["reason"],
                  "quote": c["quote"], "cited": [order[i] for i in c["valid_cited"] if i in order],
                  "removed": c["verdict"] != "SUPPORTED"} for c in claims]
    conf = confidence.compute(len(claims), len(good), cited_ev, bool(conflicts), state.get("correction_round", 0))
    ui_conflicts = [{"description": c["description"], "sources": [order[i] for i in c["ids"] if i in order]}
                    for c in conflicts]
    return {"final_answer": answer, "outcome": "answered", "citations": citations, "claims": ui_claims,
            "confidence": conf, "conflicts": ui_conflicts,
            "trace": [f"Final answer -> {len(citations)} citations, confidence {conf['label']}"]}