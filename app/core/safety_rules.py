import re

DISCLAIMER = (
    "MedVerify AI summarises published research and is not a substitute for professional "
    "medical advice, diagnosis or treatment. Always consult a qualified clinician about your "
    "own health. In an emergency, contact your local emergency services."
)

EMERGENCY_MESSAGE = (
    "Your message describes symptoms that may be a medical emergency. Please contact your local "
    "emergency number now (for example 112 in India, 911 in the US, 999 in the UK) or go to the "
    "nearest emergency department. MedVerify AI provides research information only and cannot "
    "assess urgent situations. If you were asking from a research perspective, please rephrase "
    "your question without describing personal symptoms."
)

SELF_HARM_MESSAGE = (
    "I'm really sorry you're going through this, and I'm glad you reached out. You deserve support "
    "right now. Please contact your local emergency number or a crisis line in your country, or "
    "reach out to someone you trust who can be with you. If you are in immediate danger, call "
    "emergency services. MedVerify AI is a research tool and cannot provide crisis support."
)

PERSONAL_NOTICE = (
    "This looks like a question about your personal treatment. The answer below describes what "
    "research shows in general. It cannot account for your own health, medicines or dose. "
    "Please discuss decisions with your doctor or pharmacist."
)

_FIRST_PERSON = re.compile(r"\b(i|i'm|im|i've|ive|my|me|he|she|someone|we|baby|child)\b", re.I)

_SYMPTOMS = [
    (r"chest pain|pain in (my )?chest|pressure in (my )?chest|crushing chest", "possible cardiac emergency"),
    (r"can'?t breathe|cannot breathe|trouble breathing|struggling to breathe|short(ness)? of breath", "breathing emergency"),
    (r"face (is )?droop|slurred speech|sudden (numbness|weakness)|worst headache of my life", "possible stroke"),
    (r"severe bleeding|won'?t stop bleeding|coughing up blood|vomiting blood", "severe bleeding"),
    (r"anaphyla|throat (is )?closing|swelling of (the |my )?(face|tongue|throat)", "possible anaphylaxis"),
    (r"overdos|took too many|swallowed too many", "possible overdose"),
    (r"having a seizure|unconscious|passed out|unresponsive", "loss of consciousness / seizure"),
]

_SELF_HARM = re.compile(
    r"kill myself|end my life|want to die|hurt myself|thinking (about|of) (suicide|killing myself)|"
    r"suicidal thoughts? (right now|tonight)",
    re.I,
)

_PERSONAL = re.compile(
    r"\bshould i (take|stop|start|increase|decrease|skip)\b|\bmy (dose|dosage|medication|prescription)\b|"
    r"\bhow (much|many) .{0,40}\bshould i\b|\bcan i take .{0,60}\b(with|and|together)\b|\bdo i have\b|\bam i (pregnant|dying)\b",
    re.I,
)


def check(question: str) -> dict:
    q = question.lower()
    result = {"emergency": False, "category": "", "message": "", "personalized": False}

    if _SELF_HARM.search(q):
        result.update(emergency=True, category="self-harm risk", message=SELF_HARM_MESSAGE)
        return result

    if _FIRST_PERSON.search(q):
        for pattern, category in _SYMPTOMS:
            if re.search(pattern, q):
                result.update(emergency=True, category=category, message=EMERGENCY_MESSAGE)
                return result

    if _PERSONAL.search(q):
        result["personalized"] = True
    return result