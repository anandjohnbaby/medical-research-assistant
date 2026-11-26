# MedVerify AI

**An agentic RAG assistant that answers medical research questions from trusted literature, cites every statement, and fact-checks its own answer before showing it.**

MedVerify AI retrieves evidence from a private knowledge base, live PubMed and an allowlist of trusted health websites. It generates an answer in which every sentence carries a citation. It then splits that answer into individual claims and verifies each one against its cited source. Unsupported claims are corrected or removed, and the user can inspect the full evidence trail.

> **Medical disclaimer.** MedVerify AI summarises published research. It is not a medical device and is not a substitute for professional medical advice, diagnosis or treatment. Always consult a qualified clinician about your own health. In an emergency, contact your local emergency services.

---

## Table of contents

- [What I implemented](#what-i-implemented)
- [Architecture](#architecture)
- [Run the project](#run-the-project)
- [Seeding the knowledge base](#seeding-the-knowledge-base)
- [Using the app](#using-the-app)
- [Medical-domain safeguards](#medical-domain-safeguards)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [API reference](#api-reference)
- [Configuration](#configuration)
- [Testing](#testing)
- [Engineering notes](#engineering-notes)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)

---

## What I implemented

| Area | What was built | Where |
|---|---|---|
| Agentic workflow | LangGraph state machine with safety gate, router, query understanding, retrieval, evidence grading, web fallback, generation, claim verification, correction loop and finalisation | `app/rag/` |
| Multi-source retrieval | Pinecone knowledge base with local embeddings, live PubMed search through NCBI E-utilities, and a Tavily web fallback limited to trusted domains | `app/services/vectorstore.py`, `pubmed.py`, `web_search.py` |
| Claim-level verification | Each claim is labelled `SUPPORTED`, `UNSUPPORTED` or `CONTRADICTED`. A deterministic check confirms that quoted excerpts exist in the source. | `app/rag/nodes.py` |
| Self-correction | Failing claims are rewritten or removed, then re-verified for a limited number of rounds | `app/rag/nodes.py` |
| Strict structured outputs | JSON schemas for every LLM step that returns JSON, with retries and a safe fallback | `app/rag/schemas.py`, `app/services/llm.py` |
| Medical safety rules | Emergency, self-harm and personal-treatment detection, source allowlist, evidence tiers, retraction filtering, mandatory disclaimer | `app/core/` |
| Confidence scoring | High, Moderate, Low or Insufficient, computed from verification results and evidence quality | `app/services/confidence.py` |
| Knowledge-base ingestion | PDF, DOCX, TXT and MD upload, paragraph-aware chunking, and a PubMed seeding script | `app/services/ingestion.py`, `scripts/` |
| Privacy and audit | PII redaction before logging or external calls, SQLite audit trail of evidence, verdicts and models | `app/services/pii.py`, `audit.py` |
| Backend | FastAPI with rate limiting, admin-key protection and security headers | `app/api/`, `app/main.py` |
| Frontend | Plain HTML, CSS and JavaScript chat UI with evidence, claim-check and pipeline panels | `templates/`, `static/` |
| Packaging and tests | Dockerfile, Docker Compose and offline pytest suite | repository root, `tests/` |

---

## Architecture

### Agentic RAG workflow

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 15, "rankSpacing": 20, "padding": 4}, "themeVariables": {"fontSize": "12px"}}}%%
flowchart TD
    U(["User question"]) --> S{"1. Safety gate"}
    S -- "Emergency or self-harm" --> E["Fixed safety message"]
    S -- "Clear" --> R{"2. Router (LLM)"}
    R -- "Non-medical" --> D["Direct answer"]
    R -- "Medical" --> Q["3. Query understanding"]
    Q --> K["4a. Pinecone KB search"]
    Q --> P["4b. Live PubMed search"]
    K --> G{"5. Evidence grader"}
    P --> G
    G -- "GOOD" --> GEN["7. Generate cited answer"]
    G -- "WEAK, first time" --> W["6. Trusted web search (Tavily)"]
    W --> G
    G -- "WEAK, after web" --> RW["Rewrite query"]
    RW --> Q
    G -- "WEAK, retries used" --> INS["Insufficient-evidence reply"]
    GEN --> V{"8. Claim verifier"}
    V -- "All supported" --> F["10. Finalize"]
    V -- "Failures, rounds left" --> C["9. Corrector"]
    C --> V
    V -- "Failures, no rounds left" --> F
    V -- "Nothing verified" --> INS
    F --> OUT(["Final answer"])
    INS --> OUT
    D --> OUT
    E --> OUT
```

### System components

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 15, "rankSpacing": 25, "padding": 4}, "themeVariables": {"fontSize": "12px"}}}%%
flowchart LR
    subgraph Client["Browser"]
        UI["HTML, CSS, JavaScript UI"]
    end

    subgraph Backend["FastAPI backend (Docker)"]
        API["REST API"]
        WF["LangGraph workflow"]
        SVC["Services: PII, confidence, audit, ingestion"]
        EMB["Local embeddings"]
        DB[("SQLite audit trail")]
    end

    subgraph External["Free external services"]
        LLM["Groq LLM"]
        PC[("Pinecone")]
        PM["PubMed"]
        TV["Tavily"]
    end

    UI <--> API
    API --> WF
    WF --> SVC
    WF --> LLM
    WF --> PM
    WF --> TV
    WF --> PC
    SVC --> EMB
    EMB --> PC
    SVC --> DB
```

### How a question flows

| Step | What happens |
|---|---|
| 1. Safety gate | Rule-based detection of emergencies, self-harm and personal-treatment questions. Emergencies get a fixed message and no research answer. |
| 2. Router | An LLM decides whether the message is a medical question or general conversation. |
| 3. Query understanding | The question is converted into a PubMed query and a web query. |
| 4. Retrieval | Pinecone knowledge-base search and live PubMed search run, with retracted papers excluded. Fetched PubMed papers are cached into the knowledge base in the background. |
| 5. Evidence grading | Sources are scored for relevance and ranked by study type. The result is GOOD or WEAK. |
| 6. Web fallback | If evidence is weak, Tavily searches only allowlisted domains such as nih.gov, who.int, cdc.gov and fda.gov. If it is still weak, the query is rewritten and retried a limited number of times. |
| 7. Generation | The answer may use only the numbered evidence and must cite it. |
| 8. Claim verification | Each claim is checked against its cited passage. A supported claim needs an excerpt that actually exists in the source. |
| 9. Correction | Failing claims are rewritten or removed, then re-verified for a limited number of rounds. |
| 10. Finalize | Citations are numbered, source disagreements are flagged, confidence is computed and a disclaimer is attached. If nothing could be verified, the reply is a transparent "insufficient evidence" message. |

---

## Run the project

### 1. Get free API keys

| Service | Where | Used for |
|---|---|---|
| Groq | console.groq.com | LLM inference |
| Pinecone | app.pinecone.io (Starter plan) | Vector database |
| Tavily | app.tavily.com | Trusted web search |
| NCBI (optional) | ncbi.nlm.nih.gov/account | Higher PubMed rate limit |

### 2. Configure

Windows (PowerShell):
```powershell
copy .env.example .env
```

macOS or Linux:
```bash
cp .env.example .env
```

Open `.env` and fill in your keys. Set `GROQ_FAST_MODEL` and `GROQ_STRONG_MODEL` to models your Groq key can use (this project runs on `openai/gpt-oss-20b` and `openai/gpt-oss-120b`). Never commit `.env`.

### 3a. Option A: run with Docker (recommended)

```bash
docker compose up --build -d
docker compose logs -f
```

Open <http://localhost:8000>. If port 8000 is taken, change the mapping in `docker-compose.yml`, for example `"8080:8000"`.

### 3b. Option B: run locally without Docker

Requires Python 3.10 to 3.12.

Windows (PowerShell):
```powershell
python -m venv venv
venv\Scripts\activate
pip install --default-timeout=120 --retries 10 -r requirements.txt
python run.py
```

macOS or Linux:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python run.py
```

The first start downloads the embedding model (about 90 MB). Open <http://127.0.0.1:8000>.

### 4. Check that it is healthy

```bash
curl http://localhost:8000/api/health
```

Expected: `{"status":"ok","groq":true,"pinecone":true,"tavily":true}`. A `false` value means that key is missing in `.env`.

### 5. Seed the knowledge base (optional, recommended)

See the next section.

---

## Seeding the knowledge base

Seeding is optional, since live PubMed search works without it, but it makes answers faster and richer. It loads systematic reviews, meta-analyses, randomised trials and guidelines into Pinecone.

With Docker:
```bash
# Default topics (diabetes, hypertension, statins, asthma, vitamin D,
# COVID-19 vaccines, antibiotic resistance, migraine, mammography, depression)
docker compose exec medverify python -m scripts.ingest_seed_kb

# Your own topics
docker compose exec medverify python -m scripts.ingest_seed_kb "gout treatment" "migraine prevention"
```

Without Docker (virtual environment active):
```bash
python -m scripts.ingest_seed_kb
python -m scripts.ingest_seed_kb "gout treatment" "migraine prevention"
```

Inspect what retrieval returns for a query, without involving the LLM:

Windows (PowerShell, Docker):
```powershell
Get-Content scripts\test_retrieval.py | docker compose exec -T medverify python - "Does metformin reduce cardiovascular risk?"
```

macOS, Linux or Git Bash (Docker):
```bash
docker compose exec -T medverify python - "Does metformin reduce cardiovascular risk?" < scripts/test_retrieval.py
```

Without Docker:
```bash
python -m scripts.test_retrieval "Does metformin reduce cardiovascular risk?"
```

You can also upload your own PDF, DOCX, TXT or MD files from the **Admin** panel in the UI, using your `ADMIN_API_KEY`.

---

## Using the app

Ask a medical research question, for example:

> Does metformin reduce cardiovascular risk in type 2 diabetes?

The right-hand panel explains the answer:

- **Evidence:** every cited source with study type, year, journal, PMID or DOI and the supporting passage.
- **Claim checks:** each statement with its verdict, including claims that were removed.
- **Pipeline:** the full path the agent took, with timing.

Things worth trying:

| Input | Expected behaviour |
|---|---|
| A question matching a seeded topic | Answer with knowledge-base and PubMed sources |
| A medical question outside the seeded topics | Live PubMed and possibly trusted web fallback |
| `Hello` | Direct reply, no retrieval |
| `I have chest pain and can't breathe` | Emergency message, no research answer |
| `Should I stop taking my statin?` | General research answer with a personal-advice notice |
| A fictional or nonsense medical question | Transparent "insufficient evidence" reply |

---

## Medical-domain safeguards

1. **Source allowlist.** Web search is limited to trusted health and research domains. Tavily is called with `include_domains`, and results are re-checked.
2. **Evidence hierarchy.** Meta-analyses, systematic reviews and guidelines rank above randomised trials, then observational studies, then case reports and opinion.
3. **Mandatory citations.** A statement without a valid citation fails verification.
4. **Verification is a hard gate.** Unverified claims never reach the final answer.
5. **Contradictions are surfaced.** If sources disagree, the answer says so.
6. **Retractions and age.** Retracted papers are excluded, and sources older than the configured threshold are flagged.
7. **Computed confidence.** Based on verification pass rate, best study type, number of sources and conflicts.
8. **Scope control.** Emergencies, self-harm and personal-dosing questions are handled by fixed rules, not by the LLM.
9. **Privacy.** Emails, phone numbers and similar identifiers are redacted before logging or sending queries to external APIs.
10. **Auditability.** Each answer's evidence, claim verdicts, models used and pipeline trace are logged to SQLite.

---

## Tech stack

| Layer | Technology |
|---|---|
| Orchestration | LangGraph |
| Backend | FastAPI, Pydantic, Uvicorn |
| LLM | Groq (`openai/gpt-oss-120b` and `openai/gpt-oss-20b`) |
| Embeddings | `sentence-transformers` (local, free) |
| Vector database | Pinecone Starter (free) |
| Literature | PubMed via NCBI E-utilities |
| Web fallback | Tavily (free tier, domain allowlist) |
| Frontend | HTML, CSS, JavaScript (no framework) |
| Audit store | SQLite |
| Packaging | Docker, Docker Compose |
| Tests | pytest |

---

## Project structure

```text
medverify-ai/
├── app/
│   ├── main.py                  # FastAPI app and static file serving
│   ├── api/
│   │   └── routes.py            # chat, feedback and ingestion endpoints
│   ├── core/
│   │   ├── config.py            # environment-based settings
│   │   ├── safety_rules.py      # emergency and self-harm detection
│   │   └── source_allowlist.py  # trusted domains and study-type tiers
│   ├── rag/
│   │   ├── state.py             # LangGraph state
│   │   ├── schemas.py           # JSON schemas for LLM outputs
│   │   ├── nodes.py             # workflow nodes
│   │   └── workflow.py          # graph wiring
│   └── services/
│       ├── llm.py               # Groq client with retries and structured outputs
│       ├── pubmed.py            # PubMed search and parsing
│       ├── vectorstore.py       # Pinecone and embeddings
│       ├── ingestion.py         # chunking and document loading
│       ├── web_search.py        # Tavily with domain allowlist
│       ├── confidence.py        # confidence scoring
│       ├── pii.py               # PII redaction
│       └── audit.py             # SQLite audit log
├── scripts/
│   ├── ingest_seed_kb.py        # seed the knowledge base from PubMed
│   └── test_retrieval.py        # inspect retrieval results
├── static/                      # CSS and JavaScript
├── templates/index.html         # frontend page
├── tests/test_basic.py          # offline unit tests
├── run.py                       # local development entry point
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## API reference

Interactive documentation is available at `/docs`.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Health and configuration check |
| `POST` | `/api/chat` | Ask a question. Returns the answer, citations, claim verdicts, confidence, trace and safety flags |
| `POST` | `/api/feedback` | Submit thumbs up or down for an answer |
| `POST` | `/api/ingest` | Admin only. Upload a document into the knowledge base |
| `POST` | `/api/ingest/pubmed` | Admin only. Import papers by PubMed query |

Example:

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Does vitamin D supplementation prevent fractures?"}'
```

Admin endpoints require the header `X-Admin-Key: <ADMIN_API_KEY>`.

---

## Configuration

Set these in `.env`.

| Variable | Description | Default or example |
|---|---|---|
| `GROQ_API_KEY` | Groq API key | none |
| `GROQ_FAST_MODEL` | Model for routing, grading and query rewriting | `openai/gpt-oss-20b` |
| `GROQ_STRONG_MODEL` | Model for generation and verification | `openai/gpt-oss-120b` |
| `TAVILY_API_KEY` | Tavily API key | none |
| `PINECONE_API_KEY` | Pinecone API key | none |
| `PINECONE_INDEX` | Index name, created automatically | `medverify-kb` |
| `PINECONE_NAMESPACE` | Namespace inside the index | `medical-literature` |
| `EMBEDDING_MODEL` | Local sentence-transformers model | `sentence-transformers/all-MiniLM-L6-v2` |
| `NCBI_EMAIL` | Contact email sent to NCBI | your email |
| `NCBI_API_KEY` | Optional, raises PubMed rate limit | none |
| `ADMIN_API_KEY` | Key for ingestion endpoints | a long random string |
| `RATE_LIMIT_PER_MIN` | Requests per minute per IP | `20` |
| `AUDIT_DB_PATH` | SQLite audit database path | `data/audit.db` |

Groq model availability varies by account and changes over time. List the models your key can use at console.groq.com/docs/models and set the two model variables to names from that list.

Workflow limits such as the number of retrieved passages, correction rounds and evidence age are defined in `app/core/config.py`.

If you switch to an embedding model with a different vector size, use a **new** `PINECONE_INDEX` name, because an index's dimension is fixed when it is created.

---

## Testing

Offline unit tests need no API keys:

```bash
pytest -q
# or inside the container
docker compose exec medverify pytest -q
```

They cover safety rules, PII redaction, the source allowlist, study-type tiers, chunking, excerpt grounding, claim splitting and confidence scoring.

---

## Engineering notes

Problems met while building this, and how they were solved:

- **Lock deadlock when creating the Pinecone index.** Creating the index needed the embedding model while the same non-reentrant lock was held. Switching to a re-entrant lock (`RLock`) fixed the hang on first run.
- **Unreliable JSON from reasoning models.** Groq's plain JSON mode failed with the `gpt-oss` models. Every JSON step now uses a JSON schema (strict mode on `gpt-oss-120b`, best effort on `gpt-oss-20b`), with retries and a prompt-only fallback.
- **Reasoning models running out of tokens.** Extra token headroom and low reasoning effort keep the visible answer from coming back empty.
- **Free-tier rate limits.** The LLM client retries on 429 and 5xx responses and honours the retry delay. PubMed calls are throttled to stay within NCBI limits.
- **Hallucinated verification.** A model saying "supported" is not trusted on its own. The quoted excerpt must also be found in the cited source.
- **Docker build on unstable connections.** A pip cache mount and extra retries let interrupted builds resume.

---

## Limitations

- **Not a medical device.** The claim verifier is itself LLM-based. Mandatory citations, excerpt checks and refusal on weak evidence reduce errors a lot but cannot eliminate them. Have a clinician review anything used for real decisions.
- **Abstracts only.** PubMed provides abstracts, not full text, so details found only in the full paper are not seen.
- **Rule-based emergency detection** is conservative and keyword-based. It can block some legitimate research phrasing and can miss unusual wording. It is not a triage tool.
- **Free-tier constraints.** Each question makes several LLM calls, so Groq rate limits apply. Terms and limits of all free services can change.
- **Latency.** A full run with verification and correction can take over a minute.
