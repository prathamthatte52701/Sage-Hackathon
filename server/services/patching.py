from __future__ import annotations

from dataclasses import dataclass
from difflib import unified_diff
from hashlib import sha256
from pathlib import PurePosixPath
import re


class PatchError(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


PATCH_REASON_MESSAGES = {
    "target_not_found": "The original code no longer exists at the target location.",
    "ambiguous_target": "The original code appears more than once, so the target is ambiguous.",
    "stale_source": "The source changed after the fix was generated.",
    "overlapping_patch": "This fix overlaps another generated or applied patch.",
    "malformed_fix": "The generated fix is missing a valid original or replacement snippet.",
}


def source_hash(content: str) -> str:
    return sha256((content or "").encode("utf-8")).hexdigest()


def line_span_for_offset(content: str, start: int, end: int) -> tuple[int, int]:
    before_start = content[:start]
    before_end = content[:end]
    return before_start.count("\n") + 1, before_end.count("\n") + 1


def find_exact_span(content: str, original: str) -> tuple[int, int]:
    if original is None or original == "":
        raise PatchError("malformed_fix")
    first = content.find(original)
    if first != -1:
        if content.find(original, first + 1) != -1:
            raise PatchError("ambiguous_target")
        return first, first + len(original)

    # Model output commonly normalizes Windows CRLF source to LF. Treat only
    # newline spelling as equivalent: every non-newline character remains an
    # exact match and the target must still be unique.
    normalized = original.replace("\r\n", "\n").replace("\r", "\n")
    if "\n" not in normalized:
        raise PatchError("target_not_found")
    pattern = r"\r?\n".join(re.escape(part) for part in normalized.split("\n"))
    matches = list(re.finditer(pattern, content))
    if not matches:
        raise PatchError("target_not_found")
    if len(matches) != 1:
        raise PatchError("ambiguous_target")
    return matches[0].span()


def _replacement_with_source_line_endings(content: str, fixed: str) -> str:
    """Keep a CRLF source file CRLF after applying an LF-normalized patch."""
    if "\r\n" not in content or "\n" not in fixed:
        return fixed
    return fixed.replace("\r\n", "\n").replace("\n", "\r\n")


def validate_exact_patch(
    content: str,
    original: str,
    fixed: str,
    *,
    expected_hash: str | None = None,
    existing_spans: list[tuple[int, int]] | None = None,
) -> dict:
    if not original or fixed is None or original == fixed:
        raise PatchError("malformed_fix")
    if expected_hash and expected_hash != source_hash(content):
        raise PatchError("stale_source")

    start, end = find_exact_span(content, original)
    for span_start, span_end in existing_spans or []:
        if not (end <= span_start or start >= span_end):
            raise PatchError("overlapping_patch")

    start_line, end_line = line_span_for_offset(content, start, end)
    return {
        "target_start": start,
        "target_end": end,
        "start_line": start_line,
        "end_line": end_line,
        "source_hash": source_hash(content),
    }


def build_patch_metadata(
    content: str,
    original: str,
    fixed: str,
    *,
    filename: str = "code",
    expected_hash: str | None = None,
    existing_spans: list[tuple[int, int]] | None = None,
) -> dict:
    try:
        metadata = validate_exact_patch(
            content,
            original,
            fixed,
            expected_hash=expected_hash,
            existing_spans=existing_spans,
        )
        metadata.update(
            {
                "diff": make_unified_diff(original, fixed, filename),
                "can_apply": True,
                "apply_failure_reason": "",
            }
        )
        return metadata
    except PatchError as exc:
        return {
            "diff": make_unified_diff(original or "", fixed or "", filename) if original and fixed is not None else "",
            "can_apply": False,
            "apply_failure_reason": exc.reason,
            "source_hash": source_hash(content),
        }


def apply_structured_patch(
    content: str,
    original: str,
    fixed: str,
    *,
    expected_hash: str | None = None,
    existing_spans: list[tuple[int, int]] | None = None,
) -> AppliedPatch:
    metadata = validate_exact_patch(
        content,
        original,
        fixed,
        expected_hash=expected_hash,
        existing_spans=existing_spans,
    )
    replacement = _replacement_with_source_line_endings(content, fixed or "")
    patched = content[: metadata["target_start"]] + replacement + content[metadata["target_end"] :]
    return AppliedPatch(patched=patched, diff=make_unified_diff(original, replacement))


@dataclass(frozen=True)
class AppliedPatch:
    patched: str
    diff: str


def safe_archive_path(path: str) -> str:
    normalized = str(PurePosixPath((path or "").replace("\\", "/")))
    if not normalized or normalized == ".":
        raise PatchError("malformed_fix")
    parts = PurePosixPath(normalized).parts
    if normalized.startswith("/") or ".." in parts:
        raise PatchError("malformed_fix")
    return normalized


def make_unified_diff(original: str, fixed: str, filename: str = "code") -> str:
    return "".join(
        unified_diff(
            (original or "").splitlines(keepends=True),
            (fixed or "").splitlines(keepends=True),
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            lineterm="",
        )
    )


def apply_exact_replacement(content: str, original: str, fixed: str) -> AppliedPatch:
    return apply_structured_patch(content, original, fixed)


def apply_many_exact_replacements(content: str, replacements: list[tuple[str, str]]) -> AppliedPatch:
    cursor = content
    spans = []
    for original, _fixed in replacements:
        if not original or original not in cursor:
            raise PatchError("target_not_found")
        if cursor.count(original) != 1:
            raise PatchError("ambiguous_target")
        start = cursor.index(original)
        end = start + len(original)
        if any(not (end <= a or start >= b) for a, b in spans):
            raise PatchError("overlapping_patch")
        spans.append((start, end))

    for original, fixed in replacements:
        cursor = cursor.replace(original, fixed or "", 1)
    return AppliedPatch(patched=cursor, diff=make_unified_diff(content, cursor))
