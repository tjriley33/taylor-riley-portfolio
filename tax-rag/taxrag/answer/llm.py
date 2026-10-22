"""LLM client abstraction. Anthropic API by default; Bedrock optional; None when not configured."""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from ..config import settings


def available() -> bool:
    if settings.llm_provider == "anthropic":
        return bool(settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"))
    if settings.llm_provider == "bedrock":
        return bool(os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE"))
    return False


def generate(system: str, user: str, max_tokens: int = 1800) -> Optional[dict]:
    """Returns {text, model, usage} or None if no provider configured."""
    if not available():
        return None
    if settings.llm_provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"))
        resp = client.messages.create(model=settings.llm_model, max_tokens=max_tokens, temperature=0, system=system,
                                      messages=[{"role": "user", "content": user}])
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return {"text": text, "model": resp.model, "usage": {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens}}
    if settings.llm_provider == "bedrock":
        import boto3
        rt = boto3.client("bedrock-runtime", region_name=settings.bedrock_region)
        body = json.dumps({"anthropic_version": "bedrock-2023-05-31", "max_tokens": max_tokens, "temperature": 0, "system": system,
                           "messages": [{"role": "user", "content": user}]})
        resp = rt.invoke_model(modelId=settings.bedrock_model_id, body=body, contentType="application/json")
        data = json.loads(resp["body"].read())
        text = "".join(b.get("text", "") for b in data.get("content", []))
        u = data.get("usage", {})
        return {"text": text, "model": settings.bedrock_model_id, "usage": {"input": u.get("input_tokens"), "output": u.get("output_tokens")}}
    return None


def parse_json(text: str) -> dict | None:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        try:
            return json.loads(m.group(0).replace("\n", " "))
        except json.JSONDecodeError:
            return None
