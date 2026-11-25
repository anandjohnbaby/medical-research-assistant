import operator
from typing import Annotated, TypedDict


class GraphState(TypedDict, total=False):
    question: str
    route: str                 # emergency | medical | direct
    outcome: str               # answered | insufficient | direct | emergency
    safety: dict
    pubmed_query: str
    web_query: str
    evidence: list
    grade: str                 # good | weak
    web_attempted: bool
    rewrite_count: int
    answer: str
    claims: list
    conflicts: list
    correction_round: int
    final_answer: str
    citations: list
    confidence: dict
    verification_history: Annotated[list, operator.add]
    trace: Annotated[list, operator.add]