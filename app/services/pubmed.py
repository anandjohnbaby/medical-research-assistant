import re
import threading
import time
import xml.etree.ElementTree as ET

import httpx

from app.core.config import get_settings
from app.core.source_allowlist import classify_study

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_lock = threading.Lock()
_last_call = 0.0


def _get(endpoint: str, params: dict) -> httpx.Response:
    global _last_call
    s = get_settings()
    params = {**params, "tool": "medverify-ai", "email": s.ncbi_email}
    if s.ncbi_api_key:
        params["api_key"] = s.ncbi_api_key
    gap = 0.12 if s.ncbi_api_key else 0.4  # NCBI limit: 3 req/s (10 with key)

    for attempt in range(3):
        with _lock:
            wait = _last_call + gap - time.time()
            if wait > 0:
                time.sleep(wait)
            _last_call = time.time()
        r = httpx.get(f"{BASE}/{endpoint}", params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(1.5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r
    raise RuntimeError("PubMed rate limit hit; try again shortly.")


def search_pmids(query: str, retmax: int = 6) -> list[str]:
    r = _get("esearch.fcgi", {
        "db": "pubmed",
        "term": f"({query}) AND hasabstract[text]",
        "retmax": retmax,
        "retmode": "json",
        "sort": "relevance",
    })
    return r.json().get("esearchresult", {}).get("idlist", [])


def _year(article: ET.Element) -> int:
    y = article.findtext("Journal/JournalIssue/PubDate/Year")
    if not y:
        md = article.findtext("Journal/JournalIssue/PubDate/MedlineDate") or ""
        m = re.search(r"(19|20)\d{2}", md)
        y = m.group(0) if m else None
    if not y:
        y = article.findtext("ArticleDate/Year")
    return int(y) if y and y.isdigit() else 0


def fetch_articles(pmids: list[str]) -> list[dict]:
    if not pmids:
        return []
    r = _get("efetch.fcgi", {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"})
    root = ET.fromstring(r.content)
    out = []
    for art in root.findall(".//PubmedArticle"):
        mc = art.find("MedlineCitation")
        if mc is None:
            continue
        a = mc.find("Article")
        if a is None:
            continue
        pmid = (mc.findtext("PMID") or "").strip()
        title_el = a.find("ArticleTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""

        parts = []
        for t in a.findall("Abstract/AbstractText"):
            txt = "".join(t.itertext()).strip()
            if txt:
                label = t.get("Label")
                parts.append(f"{label}: {txt}" if label else txt)
        abstract = " ".join(parts)
        if not abstract:
            continue

        pub_types = [(p.text or "").strip() for p in a.findall("PublicationTypeList/PublicationType")]
        doi = ""
        for aid in art.findall("PubmedData/ArticleIdList/ArticleId"):
            if aid.get("IdType") == "doi":
                doi = (aid.text or "").strip()

        retracted = (
            "Retracted Publication" in pub_types
            or any(c.get("RefType") == "RetractionIn"
                   for c in mc.findall("CommentsCorrectionsList/CommentsCorrections"))
            or title.lower().startswith(("retracted", "[retracted"))
        )
        out.append({
            "pmid": pmid, "title": title, "abstract": abstract,
            "journal": a.findtext("Journal/Title") or "",
            "year": _year(a), "doi": doi, "pub_types": pub_types, "retracted": retracted,
        })
    return out


def to_evidence(article: dict) -> dict:
    study_type, tier = classify_study(article["pub_types"])
    return {
        "key": f"pmid:{article['pmid']}",
        "source": "pubmed",
        "title": article["title"],
        "text": article["abstract"],
        "pmid": article["pmid"],
        "doi": article["doi"],
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{article['pmid']}/",
        "year": article["year"],
        "journal": article["journal"],
        "study_type": study_type,
        "tier": tier,
        "retracted": article["retracted"],
        "score": 0.0,
    }