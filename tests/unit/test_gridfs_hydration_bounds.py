import asyncio

import pytest

import db.mongo as mongo_module
from db.mongo import hydrate_file_content, hydrate_selected_files


def _files(n: int) -> list[dict]:
    return [{"path": f"src/f{i}.py", "content_ref": f"ref-{i}", "language": "python"} for i in range(n)]


@pytest.mark.asyncio
async def test_hydrate_never_exceeds_configured_concurrency(monkeypatch):
    """The regression this guards against: asyncio.gather over every file in
    a large project opens one GridFS download stream per file simultaneously
    -- a real crash/OOM vector at project sizes in the thousands. This proves
    the bound is real, not just present in the signature."""
    in_flight = 0
    peak = 0
    lock = asyncio.Lock()

    async def fake_fetch(content_ref: str) -> str:
        nonlocal in_flight, peak
        async with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        await asyncio.sleep(0.01)  # hold the slot long enough for overlap to show up
        async with lock:
            in_flight -= 1
        return f"content-for-{content_ref}"

    monkeypatch.setattr(mongo_module, "fetch_file_content", fake_fetch)

    files = _files(200)
    await hydrate_file_content(files, max_concurrency=8)

    assert peak <= 8
    assert all(f["content"] == f"content-for-{f['content_ref']}" for f in files)


@pytest.mark.asyncio
async def test_hydrate_selected_files_only_fetches_requested_paths(monkeypatch):
    fetched_refs = []

    async def fake_fetch(content_ref: str) -> str:
        fetched_refs.append(content_ref)
        return "x"

    monkeypatch.setattr(mongo_module, "fetch_file_content", fake_fetch)

    files = _files(50)
    target_paths = {"src/f3.py", "src/f7.py"}
    await hydrate_selected_files(files, paths=target_paths, max_concurrency=8)

    assert set(fetched_refs) == {"ref-3", "ref-7"}
    hydrated = {f["path"] for f in files if "content" in f}
    assert hydrated == target_paths


@pytest.mark.asyncio
async def test_hydrate_selected_files_skips_entries_without_content_ref(monkeypatch):
    async def fake_fetch(content_ref: str) -> str:
        return "x"

    monkeypatch.setattr(mongo_module, "fetch_file_content", fake_fetch)

    files = [{"path": "a.py", "content_ref": "ref-a"}, {"path": "b.png", "binary_ref": "bin-b"}]
    await hydrate_selected_files(files, paths=None)

    assert files[0]["content"] == "x"
    assert "content" not in files[1]
