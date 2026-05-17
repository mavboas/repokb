# Authentication

The auth subsystem supports two flows:

1. **Password login** via `src/auth/login.py`. The `login()` function returns
   an opaque session token that the caller persists.
2. **OAuth callback** via `src/auth/oauth.py`. After the user approves on the
   provider side, the provider redirects to our callback, which exchanges
   the code for a user profile.

Tokens are revoked via `logout(token)`. There is no refresh flow yet.
