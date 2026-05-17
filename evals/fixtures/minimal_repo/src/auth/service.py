"""Auth service layer with multiple classes/functions for signature testing.

Used by test_signatures.py to verify that AST extraction picks up the full
public surface — including methods, decorators, constants, and dynamic
constructs that should trip the auto-unclear heuristics.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

SESSION_TTL_SECONDS = 3600
MAX_PASSWORD_ATTEMPTS = 5
BCRYPT_ROUNDS = 12


@dataclass
class Credentials:
    """A username/password pair plus optional 2FA token."""
    username: str
    password: str
    totp_code: str | None = None


class AuthService:
    """Coordinates login, logout, and session lookup."""

    def __init__(self, session_store, password_hasher):
        self.session_store = session_store
        self.password_hasher = password_hasher

    def login(self, creds: Credentials) -> str:
        """Authenticate and return a session token."""
        if not self._verify_password(creds.username, creds.password):
            raise PermissionError("invalid credentials")
        return self.session_store.create(creds.username)

    def logout(self, token: str) -> None:
        """Revoke a session token."""
        self.session_store.revoke(token)

    def _verify_password(self, username: str, password: str) -> bool:
        stored = self.password_hasher.fetch(username)
        return self.password_hasher.verify(password, stored)


def hash_password(plain: str, salt: bytes) -> str:
    """Hash a plaintext password using sha256 + per-user salt."""
    h = hashlib.sha256()
    h.update(salt)
    h.update(plain.encode("utf-8"))
    return h.hexdigest()


async def revoke_all_sessions(user_id: int) -> int:
    """Revoke every active session for a user; returns count revoked."""
    return 0


def complex_handler(request, response, ctx, options):
    # No docstring + many branches → should trigger high-complexity AND
    # low-docstring-coverage unclear markers.
    result = []
    if not request:
        return None
    for opt in options:
        if opt == "skip":
            continue
        if opt == "abort":
            raise RuntimeError("abort requested")
        if ctx.get("dry_run"):
            result.append((opt, None))
            continue
        if opt == "default":
            result.append((opt, response.default))
        elif opt == "custom":
            result.append((opt, response.custom))
        else:
            result.append((opt, None))
    try:
        for r in result:
            if r[1] is None and ctx.get("strict"):
                raise ValueError(f"missing value for {r[0]}")
    except Exception as e:
        if ctx.get("swallow"):
            return []
        raise
    return result


def evil_lookup(obj):
    """Dynamic lookup — should trip the dynamic-construct unclear marker."""
    handler = getattr(obj, "secret_method")
    return eval("handler()")
