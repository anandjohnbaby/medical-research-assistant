import hashlib
import io
import re

from app.services import pubmed, vectorstore


def chunk_text(text: str, size: int = 1000, overlap: int = 150) -> list[str]:
    """Paragraph-aware recursive chunking with overlap."""
    text = re.sub(r"\r\n?", "\n", text).strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        while len(p) > size:
            head, p = p[:size], p[size - overlap:]
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(head)
        if len(cur) + len(p) + 2 <= size:
            cur = (cur + "\n\n" + p).strip()
        else:
            if cur:
                chunks.append(cur)
            tail = cur[-overlap:] if cur else ""
            cur = (tail + "\n\n" + p).strip() if tail else p
    if cur:
        chunks.append(cur)
    return chunks


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((p.extract_text() or "") for p in reader.pages)
    if name.endswith(".docx"):
        import docx
        d = docx.Document(io.BytesIO(data))
        return "\n\n".join(p.text for p in d.paragraphs)
    if name.endswith((".txt", ".md")):
        return data.decode("utf-8", errors="ignore")
    raise ValueError("Unsupported file type. Use PDF, DOCX, TXT or MD.")


def ingest_document(filename: str, data: bytes, source_name: str = "Uploaded document") -> int:
    text = extract_text(filename, data)
    pieces = chunk_text(text)
    if not pieces:
        raise ValueError("No readable text found in the file.")
    digest = hashlib.sha1(filename.encode() + data).hexdigest()[:10]
    chunks = [{
        "id": f"doc-{digest}-{i}",
        "embed_text": f"{filename}\n{piece}",
        "meta": {"text": piece, "title": filename, "pmid": "", "doi": "", "url": "", "year": 0,
                 "journal": source_name, "study_type": "Uploaded document", "tier": 3,
                 "retracted": False},
    } for i, piece in enumerate(pieces)]
    return vectorstore.upsert_chunks(chunks)


def articles_to_chunks(articles: list[dict]) -> list[dict]:
    chunks = []
    for art in articles:
        if art["retracted"]:
            continue
        ev = pubmed.to_evidence(art)
        for i, piece in enumerate(chunk_text(art["abstract"], size=2500, overlap=200)):
            chunks.append({
                "id": f"pmid-{art['pmid']}-{i}",
                "embed_text": f"{art['title']}\n{piece}",
                "meta": {"text": piece, "title": ev["title"], "pmid": ev["pmid"], "doi": ev["doi"],
                         "url": ev["url"], "year": ev["year"], "journal": ev["journal"],
                         "study_type": ev["study_type"], "tier": ev["tier"], "retracted": False},
            })
    return chunks


def ingest_pubmed(query: str, max_results: int = 20) -> int:
    pmids = pubmed.search_pmids(query, retmax=max_results)
    articles = pubmed.fetch_articles(pmids)
    return vectorstore.upsert_chunks(articles_to_chunks(articles))