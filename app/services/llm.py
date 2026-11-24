import json
import re
import time

import httpx

from app.core.config import get_settings

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class LLMError(RuntimeError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def _response_format(model: str, json_mode: bool, schema: dict | None, name: str):
    gpt_oss = model.startswith("openai/gpt-oss")
    if schema and gpt_oss:
        # Strict constrained decoding is documented for gpt-oss-120b; 20b is best-effort
        return {"type": "json_schema",
                "json_schema": {"name": name, "strict": model == "openai/gpt-oss-120b", "schema": schema}}
    if json_mode and not gpt_oss:
        return {"type": "json_object"}
    return None


def chat(system: str, user: str, model: str, temperature: float = 0.0,
         max_tokens: int = 1500, json_mode: bool = False,
         schema: dict | None = None, schema_name: str = "response") -> str:
    s = get_settings()
    if not s.groq_api_key:
        raise LLMError("GROQ_API_KEY is not set. Add it to your .env file.")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if model.startswith("openai/gpt-oss"):
        # Reasoning models: keep thinking short and leave room for the visible answer
        payload["reasoning_effort"] = "low"
        payload["include_reasoning"] = False
        payload["max_tokens"] = max_tokens + 1500
    rf = _response_format(model, json_mode, schema, schema_name)
    if rf:
        payload["response_format"] = rf
    headers = {"Authorization": f"Bearer {s.groq_api_key}"}

    last = ""
    for attempt in range(4):
        try:
            r = httpx.post(GROQ_URL, json=payload, headers=headers, timeout=90)
        except httpx.HTTPError as e:
            last = str(e)
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            try:
                wait = float(r.headers.get("retry-after", "0"))
            except ValueError:
                wait = 0
            last = f"HTTP {r.status_code}"
            time.sleep(min(wait or 2 * (attempt + 1), 20))
            continue
        if r.status_code >= 400:
            raise LLMError(f"Groq error {r.status_code}: {r.text[:300]}", status=r.status_code)
        content = (r.json()["choices"][0]["message"].get("content") or "").strip()
        if not content:
            last = "empty response"
            time.sleep(1)
            continue
        return content
    raise LLMError(f"Groq request failed after retries ({last}). The free tier may be rate limited; try again shortly.")


def _parse(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def chat_json(system: str, user: str, model: str, max_tokens: int = 1500,
              schema: dict | None = None, name: str = "response") -> dict:
    sys_prompt = (system + "\nRespond with a single valid JSON object only. "
                  "No explanations, no markdown, no text before or after the JSON.")
    for attempt in range(3):
        # Attempts 1-2 use the schema. The last attempt drops it and relies on the prompt.
        use_schema = schema if attempt < 2 else None
        try:
            text = chat(sys_prompt, user, model, max_tokens=max_tokens, json_mode=True,
                        schema=use_schema, schema_name=name)
        except LLMError as e:
            if e.status == 400 and attempt < 2:
                continue
            raise
        parsed = _parse(text)
        if isinstance(parsed, dict):
            return parsed
    raise LLMError("The model returned invalid JSON after several attempts.")