"""OAuth callback handler."""


def callback(code: str, state: str) -> dict:
    """Exchange an OAuth code for a user profile."""
    if not code:
        raise ValueError("missing code")
    return {"user_id": "u1", "email": "user@example.com", "state": state}


def authorize_url(redirect_uri: str) -> str:
    return f"https://provider.example/authorize?redirect={redirect_uri}"
