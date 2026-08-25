"""Mail-sending abstraction for authentication emails.

CODE MASTER AI does not bundle an email provider. In production this function
is the single integration point: wire a real SMTP/transactional-email client
here. When no provider is configured the call is a safe no-op -- it must NEVER
log the token, print it, or return it through any API surface.

Tests capture the raw verification token by monkeypatching this function
(TEST-ONLY dependency injection); the production path below cannot leak it.
"""

from __future__ import annotations

from typing import Awaitable, Callable


async def send_verification_email(email: str, token: str) -> None:
    """Deliver a verification link containing ``token`` to ``email``.

    No-op by default: there is no configured mail transport in this repository.
    The raw ``token`` is intentionally never logged or echoed here. A real
    deployment should send it only inside a one-time link such as
    ``/verify-email?token=...`` and keep it server-side otherwise.
    """
    # Intentionally does not log the token. A real implementation delivers the
    # token via a signed/opaque link and nothing else.
    return None


async def send_password_reset_email(email: str, token: str) -> None:
    """Deliver a password reset link containing ``token`` to ``email``.

    No-op by default. The raw ``token`` is intentionally never logged or echoed.
    A real deployment should send it only inside a one-time link such as
    ``/reset-password?token=...`` and keep it server-side otherwise.
    """
    return None


# TEST-ONLY hook: tests replace this callable to capture the raw token without
# a real mail server. Production never reads this.
capture_hook: Callable[[str, str], Awaitable[None]] | None = None


async def dispatch_verification_email(email: str, token: str) -> None:
    if capture_hook is not None:
        await capture_hook(email, token)
        return
    await send_verification_email(email, token)


async def dispatch_password_reset_email(email: str, token: str) -> None:
    if capture_hook is not None:
        await capture_hook(email, token)
        return
    await send_password_reset_email(email, token)
