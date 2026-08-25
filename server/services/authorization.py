"""Centralized authorization helpers for CODE MASTER AI.

All ownership and role checks must go through this module.
Frontend-only security is irrelevant -- backend must enforce.
"""

from fastapi import HTTPException, status


class AuthorizationError(HTTPException):
    """Base exception for authorization failures."""

    def __init__(self, detail: str = "Not authorized"):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def require_project_owner(project: dict | None, current_user_id: str) -> dict:
    """Verify that the current user owns the project.

    Args:
        project: Project document from get_owned_project (already ownership-checked)
        current_user_id: Current authenticated user's ID

    Returns:
        The project document if authorized

    Raises:
        AuthorizationError: If project is None (not found or not owned)
    """
    if project is None:
        raise AuthorizationError("Project not found")
    return project


def require_role(user: dict, *allowed_roles: str) -> dict:
    """Verify that the user has one of the allowed roles.

    Args:
        user: User document from get_current_user
        allowed_roles: One or more allowed role strings (e.g., "admin")

    Returns:
        The user document if authorized

    Raises:
        AuthorizationError: If user's role is not in allowed_roles
    """
    user_role = user.get("role", "user")
    if user_role not in allowed_roles:
        raise AuthorizationError(f"Requires one of roles: {', '.join(allowed_roles)}")
    return user


def require_admin(user: dict) -> dict:
    """Convenience: require admin role."""
    return require_role(user, "admin")


def require_user_or_admin(user: dict) -> dict:
    """Convenience: require at least user role (always true for authenticated users)."""
    return require_role(user, "user", "admin")


def is_admin(user: dict) -> bool:
    """Check if user has admin role without raising."""
    return user.get("role", "user") == "admin"


def is_owner(project: dict | None, user_id: str) -> bool:
    """Check if user owns project without raising."""
    if project is None:
        return False
    return project.get("owner_user_id") == user_id