from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    groq_api_key: str = ""
    groq_fast_model: str = "llama-3.1-8b-instant"
    groq_strong_model: str = "llama-3.3-70b-versatile"

    tavily_api_key: str = ""

    pinecone_api_key: str = ""
    pinecone_index: str = "medverify-kb"
    pinecone_namespace: str = "medical-literature"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    ncbi_email: str = "you@example.com"
    ncbi_api_key: str = ""

    admin_api_key: str = "change-me"
    rate_limit_per_min: int = 20
    audit_db_path: str = "data/audit.db"

    # Workflow limits
    kb_top_k: int = 6
    pubmed_max: int = 6
    max_evidence: int = 8
    max_rewrites: int = 1
    max_corrections: int = 2
    cache_pubmed_in_kb: bool = True
    old_evidence_years: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()