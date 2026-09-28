"""PKCE (RFC 7636, S256) and the CSRF ``state`` for the connect ceremony."""

from __future__ import annotations

import base64
import hashlib
import secrets


def new_verifier() -> str:
    """A fresh code verifier: 64 URL-safe characters, kept server-side until the exchange."""
    return secrets.token_urlsafe(48)


def challenge_for(verifier: str) -> str:
    """The S256 code challenge for ``verifier``: BASE64URL(SHA-256(verifier)), no padding."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def new_state() -> str:
    """A fresh ``state`` value, verified on return to the redirect URI."""
    return secrets.token_urlsafe(24)
