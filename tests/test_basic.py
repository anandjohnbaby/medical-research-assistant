from app.core import safety_rules
from app.core.source_allowlist import classify_study, is_allowed
from app.rag.nodes import quote_grounded, split_claims
from app.services import confidence
from app.services.ingestion import chunk_text
from app.services.pii import redact


def test_emergency_detected():
    assert safety_rules.check("I have chest pain and can't breathe")["emergency"]


def test_research_question_not_emergency():
    assert not safety_rules.check("What causes chest pain in athletes?")["emergency"]


def test_self_harm_detected():
    assert safety_rules.check("I want to die")["emergency"]


def test_personal_flag():
    assert safety_rules.check("Should I stop taking my statin?")["personalized"]


def test_pii_redaction():
    out = redact("mail me at a.b@example.com or call 555-123-4567")
    assert "example.com" not in out and "4567" not in out


def test_allowlist():
    assert is_allowed("https://pubmed.ncbi.nlm.nih.gov/123/")
    assert is_allowed("https://www.who.int/news")
    assert not is_allowed("https://random-health-blog.com/post")


def test_study_tiers():
    assert classify_study(["Meta-Analysis"])[1] == 1
    assert classify_study(["Randomized Controlled Trial"])[1] == 2
    assert classify_study(["Case Reports"])[1] == 5


def test_chunking_overlap_and_size():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(20))
    chunks = chunk_text(text, size=800, overlap=100)
    assert len(chunks) > 1
    assert all(len(c) < 1100 for c in chunks)


def test_quote_grounding():
    src = "Metformin reduced HbA1c by 1.1 percentage points compared with placebo."
    assert quote_grounded("reduced HbA1c by 1.1 percentage points", src)
    assert not quote_grounded("cured diabetes in all patients within a week", src)


def test_split_claims_moves_citations():
    ans = ("Summary: Drug X lowers blood pressure in adults [E1].\n"
           "Key findings:\n- Drug X reduced systolic pressure by 8 mmHg. [E1][E2]\n"
           "Limitations: Few long-term data.")
    claims = split_claims(ans)
    assert len(claims) == 2
    assert claims[1]["cited"] == ["E1", "E2"]


def test_confidence_insufficient_and_conflict_cap():
    assert confidence.compute(0, 0, [], False, 0)["label"] == "Insufficient"
    ev = [{"tier": 1, "study_type": "Meta-Analysis"}] * 3
    assert confidence.compute(5, 5, ev, True, 0)["label"] != "High"