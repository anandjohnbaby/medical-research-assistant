"""Seed the knowledge base with high-quality evidence (reviews, meta-analyses, RCTs, guidelines).

Usage:
    python -m scripts.ingest_seed_kb                      # default topics
    python -m scripts.ingest_seed_kb "migraine prevention" "gout treatment"
"""
import sys

from app.services import ingestion

DEFAULT_TOPICS = [
    "type 2 diabetes metformin",
    "hypertension treatment blood pressure",
    "statins cardiovascular prevention",
    "asthma inhaled corticosteroids",
    "vitamin D supplementation",
    "COVID-19 vaccine effectiveness",
    "antibiotic resistance",
    "migraine prevention",
    "breast cancer screening mammography",
    "depression antidepressants",
]
FILTER = ("(systematic review[pt] OR meta-analysis[pt] OR randomized controlled trial[pt] "
          "OR practice guideline[pt] OR guideline[pt])")


def main():
    topics = sys.argv[1:] or DEFAULT_TOPICS
    total = 0
    for t in topics:
        try:
            n = ingestion.ingest_pubmed(f"({t}) AND {FILTER}", max_results=15)
            print(f"[ok] {t}: {n} chunks")
            total += n
        except Exception as e:
            print(f"[fail] {t}: {e}")
    print(f"Done. {total} chunks indexed.")


if __name__ == "__main__":
    main()