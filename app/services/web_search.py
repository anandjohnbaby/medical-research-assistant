import httpx

from app.core.config import get_settings
from app.core.source_allowlist import ALLOWED_DOMAINS, is_allowed


def search(query: str, max_results: int = 5) -> list[dict]:
    s = get_settings()
    if not s.tavily_api_key:
        return []
    r = httpx.post(
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {s.tavily_api_key}"},
        json={"query": query, "search_depth": "basic", "max_results": max_results,
              "include_domains": ALLOWED_DOMAINS},
        timeout=30,
    )
    r.raise_for_status()
    out = []
    for item in r.json().get("results", []):
        url = item.get("url", "")
        if not is_allowed(url) or not item.get("content"):
            continue
        out.append({
            "key": url, "source": "web", "title": item.get("title", url),
            "text": item["content"], "pmid": "", "doi": "", "url": url,
            "year": 0, "journal": url.split("/")[2] if "//" in url else "",
            "study_type": "Official health source", "tier": 4, "retracted": False,
            "score": float(item.get("score", 0.0) or 0.0),
        })
    return out