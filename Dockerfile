# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

# CPU-only PyTorch keeps the image much smaller.
# The cache mount keeps downloaded wheels, so a retry after a dropped connection resumes quickly.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url https://download.pytorch.org/whl/cpu torch

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Bake the embedding model into the image so startup is fast
ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
RUN python -c "from sentence_transformers import SentenceTransformer as S; S('$EMBEDDING_MODEL')"

COPY app ./app
COPY static ./static
COPY templates ./templates
COPY scripts ./scripts

RUN useradd -m appuser && mkdir -p /app/data && chown -R appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]