import json
import os
import sqlite3
import time
import uuid

from app.core.config import get_settings


def _conn():
    path = get_settings().audit_db_path
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    return sqlite3.connect(path)


def init():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS audit (
            id TEXT PRIMARY KEY, ts REAL, question TEXT, outcome TEXT, confidence TEXT,
            evidence TEXT, claims TEXT, verification TEXT, trace TEXT, latency_ms INTEGER, models TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, request_id TEXT, rating TEXT, comment TEXT)""")


def log(question: str, result: dict, latency_ms: int) -> str:
    rid = uuid.uuid4().hex
    s = get_settings()
    with _conn() as c:
        c.execute("INSERT INTO audit VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            rid, time.time(), question, result.get("outcome", ""),
            result.get("confidence", {}).get("label", ""),
            json.dumps([x.get("pmid") or x.get("url") for x in result.get("citations", [])]),
            json.dumps([{k: v for k, v in cl.items() if k in ("id", "verdict")} for cl in result.get("claims", [])]),
            json.dumps(result.get("verification", [])),
            json.dumps(result.get("trace", [])),
            latency_ms, f"{s.groq_fast_model}|{s.groq_strong_model}|{s.embedding_model}",
        ))
    return rid


def feedback(request_id: str, rating: str, comment: str):
    with _conn() as c:
        c.execute("INSERT INTO feedback (ts, request_id, rating, comment) VALUES (?,?,?,?)",
                  (time.time(), request_id, rating, comment[:500]))