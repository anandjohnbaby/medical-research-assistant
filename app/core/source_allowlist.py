from urllib.parse import urlparse

# Web search is restricted to these domains (and their subdomains).
ALLOWED_DOMAINS = [
    "nih.gov",            # includes pubmed.ncbi.nlm.nih.gov, pmc.ncbi.nlm.nih.gov, cancer.gov, medlineplus.gov
    "who.int",
    "cdc.gov",
    "fda.gov",
    "ema.europa.eu",
    "nice.org.uk",
    "nhs.uk",
    "cochranelibrary.com",
    "clinicaltrials.gov",
    "europepmc.org",
    "ahrq.gov",
    "medlineplus.gov",
]


def is_allowed(url: str) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS)


def classify_study(pub_types: list[str]) -> tuple[str, int]:
    """Map PubMed publication types to (label, tier). Tier 1 = strongest evidence."""
    low = [p.lower() for p in pub_types]
    joined = " | ".join(low)

    if "meta-analysis" in joined:
        return "Meta-Analysis", 1
    if "systematic review" in joined:
        return "Systematic Review", 1
    if "practice guideline" in joined or "guideline" in joined:
        return "Clinical Guideline", 1
    if "randomized controlled trial" in joined:
        return "Randomized Controlled Trial", 2
    if "clinical trial" in joined:
        return "Clinical Trial", 3
    if any(k in joined for k in ("observational study", "cohort", "comparative study", "multicenter study")):
        return "Observational Study", 3
    if "case reports" in joined:
        return "Case Report", 5
    if any(k in joined for k in ("editorial", "comment", "letter", "news")):
        return "Opinion / Commentary", 5
    if "review" in joined:
        return "Narrative Review", 4
    return "Journal Article", 4