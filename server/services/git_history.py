"""Git truth for Commit Guard: HEAD/parent resolution, commit metadata, and
file-level diffs/content, sourced entirely from the GitHub REST API over
httpx -- the exact same transport routers/projects.py's import_from_github
already uses for the zipball fetch. Deliberately NOT a local git clone/CLI
implementation: that would mean a second, riskier repository-import path
(shell subprocess, temp directories, hook handling) when the GitHub API
already gives us everything Commit Guard needs (parent SHAs, per-file
patches, and file content at any ref) over plain HTTPS, with no local
process execution at all.

This module is READ ONLY. It never mutates the project, never executes
repository code, and never shells out.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field

import httpx

GITHUB_API = "https://api.github.com"
REQUEST_TIMEOUT = 15
# A commit can touch hundreds/thousands of files -- Commit Guard only ever
# needs to look at Python source, and only up to a bounded count of them,
# to keep both GitHub API usage (unauthenticated: 60 req/hour) and
# downstream analysis bounded regardless of how large the real commit is.
MAX_CHANGED_PYTHON_FILES = 60


class GitHistoryUnavailable(Exception):
    """Raised for anything that means "no usable git truth" -- never
    fabricate a commit/diff/parent in response to this; the caller must
    show 'Git history unavailable' instead."""


@dataclass
class ChangedFile:
    path: str
    status: str  # "added" | "modified" | "removed" | "renamed"
    previous_path: str | None = None
    additions: int = 0
    deletions: int = 0
    patch: str = ""  # unified diff hunk text, "" if GitHub omitted it (binary/huge file)


@dataclass
class CommitInfo:
    head_sha: str
    base_sha: str | None  # None only for an initial commit (no parent)
    comparison_type: str  # "parent" | "initial"
    message: str
    author: str
    authored_at: str
    merge_commit: bool
    parent_count: int
    comparison_parent: str | None  # same as base_sha when not a merge; documented separately per spec
    changed_files: list[ChangedFile] = field(default_factory=list)
    truncated: bool = False  # True if changed_files was bounded below the real total


@dataclass
class PullRequestInfo:
    number: int
    title: str
    body: str
    state: str
    merged: bool
    author: str
    base_branch: str
    head_branch: str
    base_sha: str
    head_sha: str
    merge_base_sha: str
    commit_count: int
    changed_file_count: int
    additions: int
    deletions: int
    changed_files: list[ChangedFile] = field(default_factory=list)
    truncated: bool = False


def _auth_headers() -> dict[str, str]:
    # No GITHUB_TOKEN is configured anywhere in this codebase today (the
    # existing zipball import already runs unauthenticated) -- matching
    # that rather than introducing a new required secret. Unauthenticated
    # REST calls are rate-limited to 60/hour; every call site below is
    # bounded specifically so one Commit Guard run stays well under that.
    return {"Accept": "application/vnd.github+json", "User-Agent": "sage-commit-guard"}


async def _get_json(client: httpx.AsyncClient, url: str, **params) -> dict:
    try:
        resp = await client.get(url, params=params, headers=_auth_headers(), timeout=REQUEST_TIMEOUT)
    except httpx.RequestError as exc:
        raise GitHistoryUnavailable(f"Could not reach GitHub: {exc}") from exc
    if resp.status_code == 404:
        raise GitHistoryUnavailable("Not found on GitHub")
    if resp.status_code == 403:
        raise GitHistoryUnavailable("GitHub API rate limit reached, please try again shortly")
    if resp.status_code != 200:
        raise GitHistoryUnavailable(f"GitHub declined this request ({resp.status_code})")
    return resp.json()


def _is_python_path(path: str) -> bool:
    return path.endswith(".py") or path.endswith(".pyi")


async def resolve_latest_commit(owner: str, repo: str) -> CommitInfo:
    """HEAD = the default branch's latest commit. BASE = its first parent
    (or None for an initial commit). Never an arbitrary/guessed snapshot."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        commits = await _get_json(client, f"{GITHUB_API}/repos/{owner}/{repo}/commits", per_page=1)
        if not commits:
            raise GitHistoryUnavailable("Repository has no commits")
        head_sha = commits[0]["sha"]
        return await resolve_commit(owner, repo, head_sha, client=client)


async def resolve_commit(owner: str, repo: str, head_sha: str, *, client: httpx.AsyncClient | None = None) -> CommitInfo:
    """Fetch one commit's metadata + file-level diff by SHA. head_sha must
    already be a real SHA obtained from GitHub (resolve_latest_commit, or a
    project's own stored history) -- never a raw string accepted from
    request input without having come from a prior GitHub API response."""
    owns_client = client is None
    client = client or httpx.AsyncClient(follow_redirects=True)
    try:
        data = await _get_json(client, f"{GITHUB_API}/repos/{owner}/{repo}/commits/{head_sha}")

        parents = data.get("parents") or []
        parent_count = len(parents)
        merge_commit = parent_count > 1
        comparison_parent = parents[0]["sha"] if parents else None

        files_raw = data.get("files") or []
        python_files = [f for f in files_raw if _is_python_path(f.get("filename", "")) or _is_python_path(f.get("previous_filename", ""))]
        truncated = len(python_files) > MAX_CHANGED_PYTHON_FILES
        python_files = python_files[:MAX_CHANGED_PYTHON_FILES]

        changed_files = [
            ChangedFile(
                path=f.get("filename", ""),
                status={"added": "added", "removed": "removed", "modified": "modified", "renamed": "renamed"}.get(f.get("status"), "modified"),
                previous_path=f.get("previous_filename"),
                additions=f.get("additions", 0),
                deletions=f.get("deletions", 0),
                patch=f.get("patch", "") or "",
            )
            for f in python_files
        ]

        commit_meta = data.get("commit", {})
        author_meta = commit_meta.get("author", {})

        return CommitInfo(
            head_sha=data["sha"],
            base_sha=comparison_parent,
            comparison_type="initial" if not parents else "parent",
            message=commit_meta.get("message", ""),
            author=author_meta.get("name", "unknown"),
            authored_at=author_meta.get("date", ""),
            merge_commit=merge_commit,
            parent_count=parent_count,
            comparison_parent=comparison_parent,
            changed_files=changed_files,
            truncated=truncated,
        )
    finally:
        if owns_client:
            await client.aclose()


async def resolve_pull_request(owner: str, repo: str, number: int) -> PullRequestInfo:
    """Resolve one GitHub pull request and its combined PR diff truth.

    The caller supplies only a PR number. Owner/repo come from the persisted
    GitHub-backed project, and every SHA/branch/file count below is resolved
    from GitHub, never trusted from the frontend.
    """
    if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        raise GitHistoryUnavailable("Invalid pull request number")

    async with httpx.AsyncClient(follow_redirects=True) as client:
        pr = await _get_json(client, f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}")
        base_repo = ((pr.get("base") or {}).get("repo") or {}).get("full_name", "")
        if base_repo.lower() != f"{owner}/{repo}".lower():
            raise GitHistoryUnavailable("Pull request does not belong to this repository")

        base = pr.get("base") or {}
        head = pr.get("head") or {}
        base_sha = base.get("sha") or ""
        head_sha = head.get("sha") or ""
        if not base_sha or not head_sha:
            raise GitHistoryUnavailable("Pull request is missing base/head commit data")

        compare = await _get_json(client, f"{GITHUB_API}/repos/{owner}/{repo}/compare/{base_sha}...{head_sha}")
        merge_base_sha = ((compare.get("merge_base_commit") or {}).get("sha")) or base_sha

        files: list[ChangedFile] = []
        page = 1
        while len(files) < MAX_CHANGED_PYTHON_FILES:
            batch = await _get_json(client, f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}/files", per_page=100, page=page)
            if not batch:
                break
            for item in batch:
                if len(files) >= MAX_CHANGED_PYTHON_FILES:
                    break
                files.append(
                    ChangedFile(
                        path=item.get("filename", ""),
                        status={"added": "added", "removed": "removed", "modified": "modified", "renamed": "renamed"}.get(item.get("status"), "modified"),
                        previous_path=item.get("previous_filename"),
                        additions=item.get("additions", 0),
                        deletions=item.get("deletions", 0),
                        patch=item.get("patch", "") or "",
                    )
                )
            if len(batch) < 100:
                break
            page += 1

        changed_file_count = int(pr.get("changed_files") or len(files))
        return PullRequestInfo(
            number=number,
            title=pr.get("title") or "",
            body=pr.get("body") or "",
            state=pr.get("state") or "unknown",
            merged=bool(pr.get("merged")),
            author=((pr.get("user") or {}).get("login")) or "unknown",
            base_branch=base.get("ref") or "",
            head_branch=head.get("label") or head.get("ref") or "",
            base_sha=base_sha,
            head_sha=head_sha,
            merge_base_sha=merge_base_sha,
            commit_count=int(pr.get("commits") or 0),
            changed_file_count=changed_file_count,
            additions=int(pr.get("additions") or 0),
            deletions=int(pr.get("deletions") or 0),
            changed_files=files,
            truncated=changed_file_count > len(files),
        )


async def resolve_pull_request_head_sha(owner: str, repo: str, number: int) -> str:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        pr = await _get_json(client, f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}")
        return ((pr.get("head") or {}).get("sha")) or ""


async def fetch_file_at_ref(owner: str, repo: str, path: str, ref: str, *, client: httpx.AsyncClient) -> str | None:
    """Full file content at a specific commit SHA. Returns None if the file
    doesn't exist at that ref (e.g. an added file has no BASE version, a
    removed file has no HEAD version) -- never fabricated as empty string,
    which would look like a real empty file to downstream analysis."""
    try:
        data = await _get_json(client, f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}", ref=ref)
    except GitHistoryUnavailable as exc:
        if "Not found" in str(exc):
            return None
        raise
    if data.get("encoding") != "base64":
        return None
    try:
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    except Exception:
        return None


def snapshot_to_project(snapshot: dict[str, str]) -> dict:
    """Wraps a {path: content} snapshot (from fetch_snapshot) in the same
    project["files"] shape services.analyzer.analyze_project and
    services.blast_radius.build_blast_radius already expect, so both the
    security-delta and blast-delta engines can run the existing analysis
    pipelines against a BASE/HEAD snapshot exactly as they would against a
    real uploaded project -- no separate/weaker analysis path for Commit
    Guard. Commit Guard only ever snapshots .py/.pyi files, so language is
    always "python" here.
    """
    return {
        "files": [
            {"path": path, "language": "python", "content": content, "size": len(content)}
            for path, content in snapshot.items()
        ],
        "imports": [],
        "functions": [],
        "classes": [],
        "apiEndpoints": [],
        "tests": [],
        "configs": [],
        "deploymentFiles": [],
        "findings": [],
        "warnings": [],
    }


async def fetch_snapshot(owner: str, repo: str, paths: list[str], ref: str | None) -> dict[str, str]:
    """Bounded-concurrency fetch of full file content for a list of paths at
    one ref. ref=None (used for an initial commit's BASE, which doesn't
    exist) returns an empty snapshot -- an empty repository, not an error."""
    if ref is None or not paths:
        return {}
    import asyncio

    semaphore = asyncio.Semaphore(12)  # same bound as db.mongo.GRIDFS_MAX_CONCURRENCY, same reasoning
    result: dict[str, str] = {}

    async with httpx.AsyncClient(follow_redirects=True) as client:
        async def _fetch(path: str) -> None:
            async with semaphore:
                content = await fetch_file_at_ref(owner, repo, path, ref, client=client)
                if content is not None:
                    result[path] = content

        await asyncio.gather(*(_fetch(p) for p in paths))
    return result
