# app/services/teller_provider.py

from __future__ import annotations

import hashlib
import time
from typing import Any

import httpx
import logging
import asyncio

from app.core.config import settings


class TellerRateLimiter:
    def __init__(self, limit_per_min: int) -> None:
        self.limit = max(1, limit_per_min)
        self.buckets: dict[int, list[float]] = {}

    def check(self, user_id: int) -> bool:
        now = time.time()
        window_start = now - 60
        bucket = self.buckets.get(user_id, [])
        bucket = [ts for ts in bucket if ts >= window_start]
        if len(bucket) >= self.limit:
            self.buckets[user_id] = bucket
            return False
        bucket.append(now)
        self.buckets[user_id] = bucket
        return True


class TellerCache:
    def __init__(self, ttl_seconds: int) -> None:
        self.ttl = max(1, ttl_seconds)
        self.items: dict[str, tuple[float, str]] = {}

    def _key(self, user_id: int, message: str) -> str:
        h = hashlib.sha256(message.encode("utf-8")).hexdigest()
        return f"{user_id}:{h}"

    def get(self, user_id: int, message: str) -> str | None:
        key = self._key(user_id, message)
        record = self.items.get(key)
        if not record:
            return None
        expires_at, value = record
        if time.time() > expires_at:
            self.items.pop(key, None)
            return None
        return value

    def set(self, user_id: int, message: str, response: str) -> None:
        key = self._key(user_id, message)
        self.items[key] = (time.time() + self.ttl, response)


rate_limiter = TellerRateLimiter(settings.TELLER_RATE_LIMIT_PER_MIN)
cache = TellerCache(settings.TELLER_CACHE_TTL_SECONDS)
persona_override: dict[str, str] = {}
logger = logging.getLogger("teller")


def set_persona_override(name: str | None, prompt: str | None) -> None:
    if name is None and prompt is None:
        persona_override.clear()
        return
    if name is not None:
        persona_override["name"] = name
    if prompt is not None:
        persona_override["prompt"] = prompt


def get_persona() -> tuple[str, str]:
    name = persona_override.get("name") or settings.TELLER_PERSONA_NAME
    prompt = persona_override.get("prompt") or settings.TELLER_PERSONA_PROMPT
    return name, prompt


async def _openai_response(
    message: str,
    history: list[dict[str, str]] | None = None,
    short_mode: bool = False,
) -> str:
    if not settings.OPENAI_API_KEY:
        return "The Teller is not configured yet. Please add an API key."
    name, prompt = get_persona()
    system_prompt = f"{name}: {prompt}"
    if len(system_prompt) > settings.TELLER_PROMPT_MAX_CHARS:
        system_prompt = system_prompt[: settings.TELLER_PROMPT_MAX_CHARS].rstrip() + "…"
    if short_mode:
        system_prompt += " Respond in 1-3 concise sentences."
    history_text_parts: list[str] = []
    for item in (history or []):
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            history_text_parts.append(f"{role.upper()}: {content}")
    history_text = "\n".join(history_text_parts).strip()
    full_input = f"{history_text}\nUSER: {message}".strip() if history_text else message
    payload: dict[str, Any] = {
        "model": settings.OPENAI_MODEL,
        "max_output_tokens": settings.TELLER_MAX_OUTPUT_TOKENS,
        "instructions": system_prompt,
        "input": full_input,
    }
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=20.0)) as client:
            backoffs = [0.5, 1.0, 2.0]
            for attempt, delay in enumerate(backoffs, start=1):
                try:
                    res = await client.post(
                        "https://api.openai.com/v1/responses",
                        json=payload,
                        headers=headers,
                    )
                    if res.status_code >= 400:
                        logger.warning("OpenAI error status=%s body=%s", res.status_code, res.text[:800])
                        return "I’m having trouble connecting right now. Please try again in a moment."
                    data = res.json()
                    logger.debug("OpenAI response payload=%s", str(data)[:1200])
                    text = _extract_response_text(data)
                    if text and text != "The Teller is thinking. Please try again.":
                        return _dedupe_text(text)
                    if data.get("status") == "incomplete" and data.get("incomplete_details", {}).get("reason") == "max_output_tokens":
                        logger.warning("OpenAI incomplete (max_output_tokens).")
                        return "I’m here. Please try again in a moment."
                    return text
                except httpx.ConnectTimeout as exc:
                    logger.warning("OpenAI connect timeout (attempt %s): %s", attempt, str(exc))
                    if attempt < len(backoffs):
                        await asyncio.sleep(delay)
                        continue
                    return "Connection timed out. Please try again shortly."
            return "Connection timed out. Please try again shortly."
    except httpx.HTTPError as exc:
        logger.exception("OpenAI HTTP error: %s", str(exc))
        return "I’m having trouble connecting right now. Please try again in a moment."
    return "I’m having trouble connecting right now. Please try again in a moment."


def _extract_response_text(data: dict[str, Any]) -> str:
    if "output_text" in data and isinstance(data["output_text"], str):
        return data["output_text"]
    output = data.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            content = item.get("content") if isinstance(item, dict) else None
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "output_text":
                        text = block.get("text")
                        if text:
                            parts.append(text)
                    if isinstance(block, dict) and block.get("text"):
                        parts.append(block.get("text"))
        if parts:
            return "\n".join(parts)
    message = data.get("message")
    if isinstance(message, str) and message:
        return message
    logger.warning("OpenAI response missing text fields. payload=%s", str(data)[:1200])
    return "The Teller is thinking. Please try again."


def _dedupe_text(text: str) -> str:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return text
    deduped: list[str] = []
    seen = set()
    for line in lines:
        if line in seen:
            continue
        deduped.append(line)
        seen.add(line)
    result = "\n".join(deduped).strip()
    # Collapse repeated sentences in a single line
    parts = [p.strip() for p in result.replace("  ", " ").split(".") if p.strip()]
    collapsed: list[str] = []
    last = None
    for p in parts:
        if p == last:
            continue
        collapsed.append(p)
        last = p
    if collapsed:
        return ". ".join(collapsed) + ("" if result.endswith(".") else "")
    return result


async def generate_teller_reply(
    user_id: int,
    message: str,
    history: list[dict[str, str]] | None = None,
    short_mode: bool = False,
) -> tuple[bool, str]:
    cached = cache.get(user_id, message)
    if cached:
        return True, cached

    provider = (settings.TELLER_PROVIDER or "stub").lower()
    if provider == "openai":
        reply = await _openai_response(message, history=history, short_mode=short_mode)
    else:
        reply = "How can I help you today?"

    if reply and len(reply) > settings.TELLER_MAX_CHARS:
        reply = reply[: settings.TELLER_MAX_CHARS].rstrip() + "…"

    cache.set(user_id, message, reply)
    return False, reply
