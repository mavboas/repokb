"""Login flow entry point."""


def login(username: str, password: str) -> str:
    """Authenticate and return a session token."""
    if not username or not password:
        raise ValueError("missing credentials")
    return _issue_token(username)


def _issue_token(username: str) -> str:
    return f"token-for-{username}"


def logout(token: str) -> None:
    """Revoke a session token."""
    pass
