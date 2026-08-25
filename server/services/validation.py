"""Request validation utilities for Phase 5 API hardening.

Centralizes validation logic to ensure consistent enforcement across all endpoints.
"""

from typing import Any
from pydantic import BaseModel, ValidationError


class ValidationError(Exception):
    """Raised when request validation fails with a safe, user-facing message."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def validate_model_or_error(model_cls: type[BaseModel], data: dict) -> BaseModel:
    """
    Validate a dict against a Pydantic model, raising ValidationError with safe message.

    Never exposes internal validation details or stack traces to the client.
    """
    try:
        return model_cls.model_validate(data)
    except ValidationError as exc:
        # Extract a safe, user-facing message
        errors = exc.errors()
        if errors:
            first = errors[0]
            field = ".".join(str(x) for x in first.get("loc", []))
            msg = first.get("msg", "Invalid input")
            if field:
                raise ValidationError(f"Invalid {field}: {msg}")
            raise ValidationError(msg)
        raise ValidationError("Invalid request")


def validate_required_fields(data: dict, required: list[str]) -> None:
    """Validate that all required fields are present and non-empty."""
    for field in required:
        if field not in data or data[field] is None or (isinstance(data[field], str) and data[field].strip() == ""):
            raise ValidationError(f"Missing required field: {field}")


def validate_string_length(value: str, field: str, min_len: int = 1, max_len: int = 10000) -> None:
    """Validate string field length."""
    if not isinstance(value, str):
        raise ValidationError(f"Field {field} must be a string")
    if len(value) < min_len:
        raise ValidationError(f"Field {field} must be at least {min_len} characters")
    if len(value) > max_len:
        raise ValidationError(f"Field {field} exceeds maximum length of {max_len} characters")


def validate_allowed_values(value: Any, field: str, allowed: list) -> None:
    """Validate that a field's value is in the allowed list."""
    if value not in allowed:
        raise ValidationError(f"Invalid value for {field}. Allowed: {', '.join(str(x) for x in allowed)}")


def validate_numeric_range(value: float, field: str, min_val: float = None, max_val: float = None) -> None:
    """Validate numeric field is within bounds."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValidationError(f"Field {field} must be a number")
    if min_val is not None and value < min_val:
        raise ValidationError(f"Field {field} must be at least {min_val}")
    if max_val is not None and value > max_val:
        raise ValidationError(f"Field {field} must not exceed {max_val}")


def sanitize_error_message(exc: Exception, fallback: str = "Request failed") -> str:
    """
    Extract a safe, user-facing error message from any exception.

    Never exposes internal details, stack traces, or sensitive data.
    """
    if isinstance(exc, ValidationError):
        return exc.message
    if isinstance(exc, ValueError):
        return str(exc)
    if isinstance(exc, KeyError):
        return "Invalid request data"
    # Generic fallback for unexpected errors
    return fallback


# JSON size limits for different endpoint categories
MAX_JSON_SIZE = {
    "review": 10000,      # Code snippets
    "paste_fix": 10000,   # Code + issue
    "explain": 15000,     # Code + context
    "chat": 5000,         # Question
    "github": 500,        # Repo URL
    "default": 5000,      # General
}


def get_max_json_size(endpoint: str) -> int:
    """Get the maximum allowed JSON body size for an endpoint."""
    for prefix, size in MAX_JSON_SIZE.items():
        if endpoint.startswith(f"/api/review") and prefix == "review":
            return size
        if endpoint.startswith(f"/api/review/fix") and prefix == "paste_fix":
            return size
        if endpoint.startswith(f"/api/explain") and prefix == "explain":
            return size
        if endpoint.startswith(f"/api/projects") and prefix == "chat":
            return size
        if endpoint.startswith(f"/api/projects/github") and prefix == "github":
            return size
    return MAX_JSON_SIZE["default"]