import logging
import secrets
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.rag import workflow
from app.services import audit, ingestion, llm
from app.services.pii import redact

log = logging.getLogger("medverify")
router = APIRouter(prefix="/api")

_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(request: Request):
    ip = request.client.host if request.client else "anon"
    now = time.time()
    q = _hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= get_settings().rate_limit_per_min:
        raise HTTPException(429, "Too many requests. Please wait a minute.")
    q.append(now)


def admin_auth(x_admin_key: str = Header(default="")):
    expected = get_settings().admin_api_key.encode()
    if not secrets.compare_digest(x_admin_key.encode(), expected):
        raise HTTPException(401, "Invalid admin key.")


class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class FeedbackRequest(BaseModel):
    request_id: str
    rating: str = Field(pattern="^(up|down)$")
    comment: str = ""


class PubmedIngestRequest(BaseModel):
    query: str = Field(min_length=3, max_length=300)
    max_results: int = Field(default=20, ge=1, le=100)


@router.get("/health")
def health():
    s = get_settings()
    return {"status": "ok", "groq": bool(s.groq_api_key), "pinecone": bool(s.pinecone_api_key),
            "tavily": bool(s.tavily_api_key)}


@router.post("/chat", dependencies=[Depends(rate_limit)])
async def chat(req: ChatRequest):
    question = redact(req.question.strip())
    t0 = time.time()
    try:
        result = await run_in_threadpool(workflow.run, question)
    except llm.LLMError as e:
        raise HTTPException(502, str(e))
    except Exception:
        log.exception("chat failed")
        raise HTTPException(500, "Something went wrong while processing the question.")
    latency = int((time.time() - t0) * 1000)
    result["request_id"] = audit.log(question, result, latency)
    result["latency_ms"] = latency
    return result


@router.post("/feedback")
def feedback(req: FeedbackRequest):
    audit.feedback(req.request_id, req.rating, req.comment)
    return {"ok": True}


@router.post("/ingest", dependencies=[Depends(admin_auth)])
async def ingest(file: UploadFile = File(...), source_name: str = Form("Uploaded document")):
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 15 MB).")
    try:
        n = await run_in_threadpool(ingestion.ingest_document, file.filename or "upload", data, source_name[:100])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"chunks_indexed": n}


@router.post("/ingest/pubmed", dependencies=[Depends(admin_auth)])
async def ingest_pubmed(req: PubmedIngestRequest):
    n = await run_in_threadpool(ingestion.ingest_pubmed, req.query, req.max_results)
    return {"chunks_indexed": n}