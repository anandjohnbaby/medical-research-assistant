TIER_SCORE = {1: 1.0, 2: 0.85, 3: 0.6, 4: 0.4, 5: 0.25}


def compute(total_claims: int, supported: int, cited_evidence: list[dict],
            has_conflict: bool, correction_rounds: int) -> dict:
    if total_claims == 0 or supported == 0 or not cited_evidence:
        return {"label": "Insufficient", "score": 0.0, "reasons": ["No statements could be verified."]}

    support_rate = supported / total_claims
    best = max(cited_evidence, key=lambda e: TIER_SCORE.get(e["tier"], 0.4))
    best_score = TIER_SCORE.get(best["tier"], 0.4)
    count_score = min(len(cited_evidence) / 3, 1.0)

    score = 0.4 * support_rate + 0.3 * best_score + 0.2 * count_score + 0.1 * (0 if has_conflict else 1)
    score -= 0.05 * correction_rounds
    score = max(0.0, min(1.0, score))

    label = "High" if score >= 0.75 else "Moderate" if score >= 0.5 else "Low"
    if has_conflict and label == "High":
        label = "Moderate"

    reasons = [
        f"{supported} of {total_claims} statements were verified against the sources.",
        f"Strongest source type: {best['study_type']}.",
        f"{len(cited_evidence)} distinct source(s) cited.",
    ]
    if has_conflict:
        reasons.append("Sources disagree on at least one point.")
    if correction_rounds:
        reasons.append(f"The answer needed {correction_rounds} correction round(s).")
    return {"label": label, "score": round(score, 2), "reasons": reasons}