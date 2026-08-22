import httpx
import pytest

from services import groq_client
from services.groq_client import GroqUnavailableError, call_groq


class _FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if self._json_data is None:
            raise ValueError("no json body")
        return self._json_data


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient(timeout=...). `responses` is a list
    consumed in order across all .post() calls (across attempts/keys)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, headers=None, json=None):
        self.calls += 1
        if not self.responses:
            raise AssertionError("no more fake responses queued")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _patch_client(monkeypatch, responses):
    fake = _FakeAsyncClient(responses)
    monkeypatch.setattr(groq_client.httpx, "AsyncClient", lambda timeout=None: fake)
    monkeypatch.setattr(groq_client, "GROQ_API_KEYS", ["key-a", "key-b", "key-c"])
    return fake


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    # Don't actually sleep in tests.
    monkeypatch.setattr(groq_client, "BACKOFF_BASE_SECONDS", 0)
    # Production intentionally shares one client for connection reuse; every
    # test needs its own mocked transport instead.
    monkeypatch.setattr(groq_client, "_client", None)


@pytest.mark.asyncio
async def test_success_on_first_attempt(monkeypatch):
    fake = _patch_client(
        monkeypatch,
        [_FakeResponse(200, {"choices": [{"message": {"content": "hello"}}]})],
    )
    result = await call_groq([{"role": "user", "content": "hi"}])
    assert result == "hello"
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_transient_5xx_is_retried_then_succeeds(monkeypatch):
    fake = _patch_client(
        monkeypatch,
        [
            _FakeResponse(503, text="service unavailable"),
            _FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]}),
        ],
    )
    result = await call_groq([{"role": "user", "content": "hi"}])
    assert result == "ok"
    assert fake.calls == 2


@pytest.mark.asyncio
async def test_429_rotates_key_and_retries(monkeypatch):
    fake = _patch_client(
        monkeypatch,
        [
            _FakeResponse(429, text="rate limited"),
            _FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]}),
        ],
    )
    result = await call_groq([{"role": "user", "content": "hi"}])
    assert result == "ok"
    assert fake.calls == 2


@pytest.mark.asyncio
async def test_permanent_400_fails_fast_without_exhausting_retries(monkeypatch):
    fake = _patch_client(monkeypatch, [_FakeResponse(400, text="bad request: invalid schema")])
    with pytest.raises(GroqUnavailableError, match="permanent error 400"):
        await call_groq([{"role": "user", "content": "hi"}])
    # Only one call made -- a permanent error must not consume the retry budget.
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_permanent_404_unknown_model_fails_fast(monkeypatch):
    fake = _patch_client(monkeypatch, [_FakeResponse(404, text="model not found")])
    with pytest.raises(GroqUnavailableError, match="permanent error 404"):
        await call_groq([{"role": "user", "content": "hi"}])
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_malformed_json_response_is_retried(monkeypatch):
    fake = _patch_client(
        monkeypatch,
        [
            _FakeResponse(200, json_data=None),  # .json() raises ValueError
            _FakeResponse(200, {"choices": [{"message": {"content": "recovered"}}]}),
        ],
    )
    result = await call_groq([{"role": "user", "content": "hi"}])
    assert result == "recovered"
    assert fake.calls == 2


@pytest.mark.asyncio
async def test_missing_choices_in_response_is_retried_not_crashed(monkeypatch):
    fake = _patch_client(
        monkeypatch,
        [
            _FakeResponse(200, {"unexpected": "shape"}),  # KeyError on ["choices"]
            _FakeResponse(200, {"choices": [{"message": {"content": "recovered"}}]}),
        ],
    )
    result = await call_groq([{"role": "user", "content": "hi"}])
    assert result == "recovered"
    assert fake.calls == 2


@pytest.mark.asyncio
async def test_timeout_is_retried_then_raises_after_exhausting_attempts(monkeypatch):
    fake = _patch_client(
        monkeypatch,
        [
            httpx.TimeoutException("timed out"),
            httpx.TimeoutException("timed out"),
            httpx.TimeoutException("timed out"),
        ],
    )
    with pytest.raises(GroqUnavailableError):
        await call_groq([{"role": "user", "content": "hi"}])
    assert fake.calls == 3  # MAX_ATTEMPTS, bounded -- not infinite


@pytest.mark.asyncio
async def test_no_api_keys_raises_immediately(monkeypatch):
    monkeypatch.setattr(groq_client, "GROQ_API_KEYS", [])
    with pytest.raises(GroqUnavailableError, match="GROQ_KEYS"):
        await call_groq([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_request_includes_bounded_max_tokens(monkeypatch):
    captured = {}

    class _CapturingClient(_FakeAsyncClient):
        async def post(self, url, headers=None, json=None):
            captured.update(json or {})
            return await super().post(url, headers=headers, json=json)

    fake = _CapturingClient([_FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})])
    monkeypatch.setattr(groq_client.httpx, "AsyncClient", lambda timeout=None: fake)
    monkeypatch.setattr(groq_client, "GROQ_API_KEYS", ["key-a"])

    await call_groq([{"role": "user", "content": "hi"}])
    assert "max_tokens" in captured
    assert isinstance(captured["max_tokens"], int)
    assert captured["max_tokens"] > 0


@pytest.mark.asyncio
async def test_request_sets_low_reasoning_effort(monkeypatch):
    # GROQ_MODEL is a reasoning model (openai/gpt-oss-120b): hidden
    # chain-of-thought tokens are billed against max_tokens before any
    # "content" is emitted. At default effort this was observed consuming
    # the entire token budget (finish_reason="length", content="",
    # reasoning_tokens=1998/2000), producing 0 findings on real snippets even
    # though the model had real things to say. "low" keeps CoT bounded
    # (observed ~115-235 reasoning tokens vs 700-2000) so content is reliably
    # emitted. Regression guard: this must not silently regress back to the
    # provider default.
    captured = {}

    class _CapturingClient(_FakeAsyncClient):
        async def post(self, url, headers=None, json=None):
            captured.update(json or {})
            return await super().post(url, headers=headers, json=json)

    fake = _CapturingClient([_FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})])
    monkeypatch.setattr(groq_client.httpx, "AsyncClient", lambda timeout=None: fake)
    monkeypatch.setattr(groq_client, "GROQ_API_KEYS", ["key-a"])

    await call_groq([{"role": "user", "content": "hi"}])
    assert captured.get("reasoning_effort") == "low"
