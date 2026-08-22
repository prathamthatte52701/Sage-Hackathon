import asyncio
import itertools
import time

import httpx

from config import GROQ_API_KEYS, GROQ_API_URL, GROQ_MODEL

COOLDOWN_SECONDS = 120
TIMEOUT_SECONDS = 20
MAX_ATTEMPTS = 3
# GROQ_MODEL (openai/gpt-oss-120b) is a reasoning model: hidden chain-of-thought
# tokens are billed against max_tokens before any "content" is emitted, and at
# default reasoning effort that CoT is unbounded -- observed eating all 2000
# tokens with 0 left for the JSON answer (finish_reason="length", content="",
# reasoning_tokens=1998), non-deterministically, even at temperature=0.
# reasoning_effort="low" is the real fix (observed reasoning_tokens ~115-235
# instead of 700-2000, finish_reason="stop" every time). MAX_OUTPUT_TOKENS is
# bumped too, as headroom against an occasional larger spike, not as the
# primary fix.
MAX_OUTPUT_TOKENS = 3000
REASONING_EFFORT = "low"
BACKOFF_BASE_SECONDS = 0.5  # attempt 1 waits 0s, attempt 2 waits 0.5s, attempt 3 waits 1.0s

# 429 (rate limit) and 5xx (provider-side) are transient -- worth a retry,
# optionally on a different key. Anything else >=400 (400 malformed request,
# 404 unknown model, 422 schema-invalid) is a permanent error: retrying the
# exact same broken request against a different key wastes the entire retry
# budget confirming what the first response already told us.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

_key_cycle = itertools.cycle(GROQ_API_KEYS)
_cooldowns = {}  # key -> unix timestamp until which it's skipped
_client: httpx.AsyncClient | None = None
_client_loop: asyncio.AbstractEventLoop | None = None
_client_lock = asyncio.Lock()


class GroqUnavailableError(Exception):
    pass


async def get_groq_client() -> httpx.AsyncClient:
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    # App serving uses one loop, while tests and some embedded hosts may use
    # several. An httpx transport cannot be safely reused after its loop was
    # closed, so replace it instead of poisoning later requests.
    if _client is None or _client_loop is not loop:
        async with _client_lock:
            if _client is None or _client_loop is not loop:
                _client = httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
                _client_loop = loop
    return _client


async def close_groq_client() -> None:
    global _client, _client_loop
    if _client is not None:
        close = getattr(_client, "aclose", None)
        if close is not None:
            await close()
        _client = None
        _client_loop = None


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

    client = await get_groq_client()
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
                        "reasoning_effort": REASONING_EFFORT,
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
