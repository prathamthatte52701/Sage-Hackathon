import itertools
import time

import httpx

from config import GROQ_API_KEYS, GROQ_API_URL, GROQ_MODEL

COOLDOWN_SECONDS = 120
TIMEOUT_SECONDS = 20
MAX_ATTEMPTS = 3

if not GROQ_API_KEYS:
    raise RuntimeError("GROQ_KEYS not set in environment")

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
    last_error = None
    tried_keys = set()

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        for _ in range(MAX_ATTEMPTS):
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
                    },
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                continue
            except httpx.RequestError as exc:
                last_error = exc
                continue

            if response.status_code in (401, 429):
                _mark_cooldown(key)
                last_error = Exception(f"Groq key rejected: {response.status_code}")
                continue

            if response.status_code >= 400:
                last_error = Exception(f"Groq error {response.status_code}: {response.text}")
                continue

            data = response.json()
            return data["choices"][0]["message"]["content"]

    raise GroqUnavailableError(str(last_error) if last_error else "All Groq attempts failed")
