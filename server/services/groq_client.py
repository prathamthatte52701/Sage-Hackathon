import asyncio
import itertools
import time

import httpx

from config import GROQ_API_KEYS, GROQ_API_URL, GROQ_MODEL

COOLDOWN_SECONDS = 120
TIMEOUT_SECONDS = 20
MAX_ATTEMPTS = 3
MAX_OUTPUT_TOKENS = 2000
BACKOFF_BASE_SECONDS = 0.5  # attempt 1 waits 0s, attempt 2 waits 0.5s, attempt 3 waits 1.0s

# 429 (rate limit) and 5xx (provider-side) are transient -- worth a retry,
# optionally on a different key. Anything else >=400 (400 malformed request,
# 404 unknown model, 422 schema-invalid) is a permanent error: retrying the
# exact same broken request against a different key wastes the entire retry
# budget confirming what the first response already told us.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

_key_cycle = itertools.cycle(GROQ_API_KEYS)
_cooldowns = {}  # key -> unix timestamp until which it's skipped


class GroqUnavailableError(Exception):
    pass


def _next_key():
    now = time.time()
    for _ in range(len(GROQ_API_KEYS)):
        key = next(_key_cycle)
        if _cooldowns.get(key, 0) <= now:
            return key
    # all keys cooling down, use next one anyway
    return next(_key_cycle)


def _mark_cooldown(key):
    _cooldowns[key] = time.time() + COOLDOWN_SECONDS


async def call_groq(messages: list[dict], temperature: float = 0.0) -> str:
    if not GROQ_API_KEYS:
        raise GroqUnavailableError("GROQ_KEYS not set in environment")

    last_error = None
    tried_keys = set()

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        for attempt in range(MAX_ATTEMPTS):
            if attempt > 0:
                await asyncio.sleep(BACKOFF_BASE_SECONDS * attempt)

            key = _next_key()
            if key in tried_keys and len(tried_keys) < len(GROQ_API_KEYS):
                key = _next_key()
            tried_keys.add(key)

            try:
                response = await client.post(
                    GROQ_API_URL,
                    headers={"Authorization": f"Bearer {key}"},
                    json={
                        "model": GROQ_MODEL,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": MAX_OUTPUT_TOKENS,
                    },
                )
            except httpx.TimeoutException as exc:
                last_error = f"timeout: {exc}"
                continue
            except httpx.RequestError as exc:
                last_error = f"network error: {exc}"
                continue

            if response.status_code == 401:
                # Key-specific failure, not necessarily an account-wide
                # outage -- cool this key down and try the next one.
                _mark_cooldown(key)
                last_error = f"key rejected (401): {response.text[:200]}"
                continue

            if response.status_code == 429:
                _mark_cooldown(key)
                last_error = f"rate limited (429): {response.text[:200]}"
                continue

            if response.status_code in _RETRYABLE_STATUS:
                last_error = f"provider error {response.status_code}: {response.text[:200]}"
                continue

            if response.status_code >= 400:
                # Permanent error (malformed request, unknown model, schema
                # rejected, ...): retrying the identical request won't help,
                # every key will hit the same failure. Fail fast instead of
                # burning the rest of the retry budget confirming it.
                raise GroqUnavailableError(
                    f"Groq permanent error {response.status_code}: {response.text[:300]}"
                )

            try:
                data = response.json()
                return data["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                # Malformed/unexpected response shape -- treat as retryable,
                # a transient provider hiccup rather than assume it's permanent.
                last_error = f"malformed response: {type(exc).__name__}: {exc}"
                continue

    raise GroqUnavailableError(str(last_error) if last_error else "All Groq attempts failed")
