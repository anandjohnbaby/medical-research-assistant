import threading

from app.core.config import get_settings

_embedder = None
_index = None
_lock = threading.RLock()


def get_embedder():
    global _embedder
    with _lock:
        if _embedder is None:
            from sentence_transformers import SentenceTransformer
            _embedder = SentenceTransformer(get_settings().embedding_model)
    return _embedder


def embed(texts: list[str]) -> list[list[float]]:
    vecs = get_embedder().encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vecs.tolist()


def get_index():
    global _index
    with _lock:
        if _index is not None:
            return _index
        s = get_settings()
        if not s.pinecone_api_key:
            raise RuntimeError("PINECONE_API_KEY is not set.")
        from pinecone import Pinecone, ServerlessSpec

        pc = Pinecone(api_key=s.pinecone_api_key)
        if s.pinecone_index not in pc.list_indexes().names():
            dim = get_embedder().get_sentence_embedding_dimension()
            pc.create_index(
                name=s.pinecone_index, dimension=dim, metric="cosine",
                spec=ServerlessSpec(cloud=s.pinecone_cloud, region=s.pinecone_region),
            )
            import time
            while not pc.describe_index(s.pinecone_index).status["ready"]:
                time.sleep(1)
        _index = pc.Index(s.pinecone_index)
        return _index


def _clean(meta: dict) -> dict:
    out = {}
    for k, v in meta.items():
        if v is None:
            continue
        out[k] = v if isinstance(v, (str, int, float, bool)) else str(v)
    return out


def upsert_chunks(chunks: list[dict]) -> int:
    """chunks: [{'id', 'embed_text', 'meta'}]"""
    if not chunks:
        return 0
    s = get_settings()
    index = get_index()
    total = 0
    for i in range(0, len(chunks), 64):
        batch = chunks[i:i + 64]
        vectors = embed([c["embed_text"] for c in batch])
        index.upsert(
            vectors=[{"id": c["id"], "values": v, "metadata": _clean(c["meta"])}
                     for c, v in zip(batch, vectors)],
            namespace=s.pinecone_namespace,
        )
        total += len(batch)
    return total


def query_kb(text: str, top_k: int = 6) -> list[dict]:
    s = get_settings()
    res = get_index().query(
        vector=embed([text])[0], top_k=top_k,
        namespace=s.pinecone_namespace, include_metadata=True,
    )
    out = []
    for m in res.matches:
        md = dict(m.metadata or {})
        if md.get("retracted"):
            continue
        pmid = md.get("pmid", "")
        out.append({
            "key": f"pmid:{pmid}" if pmid else m.id,
            "source": "kb",
            "title": md.get("title", ""),
            "text": md.get("text", ""),
            "pmid": pmid,
            "doi": md.get("doi", ""),
            "url": md.get("url", ""),
            "year": int(md.get("year", 0) or 0),
            "journal": md.get("journal", ""),
            "study_type": md.get("study_type", "Journal Article"),
            "tier": int(md.get("tier", 4) or 4),
            "retracted": False,
            "score": float(m.score or 0.0),
        })
    return out