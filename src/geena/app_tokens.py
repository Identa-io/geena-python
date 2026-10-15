"""App tokens: an app that signs its own users in signs a short-lived token for each of them.

The page sends the token as the bearer on ``/partner/v1`` and ``/org/v1``, straight from the
browser: no client secret, no code exchange, no refresh token, no call from your backend to
Geena. Geena verifies every token with the public key registered on the app (Organization →
Apps → *This app signs its own tokens*) and decides again, live, on every call: the app is
enabled, ``sub`` is connected to a Geena account for the app, that account's authorization of
the app stands and, on ``/org/v1``, the person is still a member whose role covers the act. A
refused token answers ``401``; the reason is never returned.

Three kinds, never interchangeable — each place refuses the other two
(https://docs.test.geena.eu/partner-api/app-tokens/):

- a **data token** (no ``token_use``): the bearer on both planes, reusable until it expires;
- a **connect hint** (``token_use: connect``): connects a member's account at your app to their
  Geena account, once, in the organization-access ceremony (:meth:`OAuthClient.connect_url`);
- a **claim link** (``token_use: claim``): opens Geena's claim page for a person your
  organization imported (:meth:`GeenaClient.claim_url`).

Never mint a token while someone at your app is impersonating a user: the token is the user.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final

import jwt

#: The longest a token may live: ``exp`` at most ten minutes after ``iat``.
MAX_LIFETIME: Final = timedelta(minutes=10)

#: Every algorithm an app may register its key for.
ALGORITHMS: Final = frozenset(
    {"ES256", "ES384", "ES512", "EdDSA", "RS256", "RS384", "RS512", "PS256", "PS384", "PS512"}
)


class TokenUse(StrEnum):
    """What a token is for. A data token carries no ``token_use`` claim at all."""

    DATA = ""
    CONNECT = "connect"
    CLAIM = "claim"


@dataclass(frozen=True)
class AppToken:
    """A signed token and when it stops working; mint the next one before ``expires_at``."""

    token: str
    expires_at: datetime

    def expires_within(self, delta: timedelta, *, now: datetime | None = None) -> bool:
        return self.expires_at - (now or datetime.now(UTC)) <= delta


class AppTokenSigner:
    """Signs your app's tokens with the private half of the key registered on your apps.

    One key may serve several apps of your organization (an investor app and a staff app, say):
    the app is ``client_id`` on every call and becomes the token's ``azp``. ``issuer`` is the
    ``iss`` registered on those apps; ``audience`` is the API the tokens are for
    (``https://api.test.geena.eu`` on test). ``private_key`` is a PEM; one passed through an
    environment variable with literal ``\\n`` is accepted as is. Keep it on your backend.
    """

    def __init__(
        self,
        *,
        issuer: str,
        private_key: str,
        audience: str,
        algorithm: str = "ES256",
        key_id: str | None = None,
        lifetime: timedelta = MAX_LIFETIME,
    ) -> None:
        if not issuer:
            raise ValueError("issuer is required: the iss registered on your apps")
        if not audience:
            raise ValueError("audience is required: the Geena API the tokens are for")
        if algorithm not in ALGORITHMS:
            raise ValueError(f"algorithm {algorithm!r} is not one Geena accepts")
        if not timedelta(0) < lifetime <= MAX_LIFETIME:
            raise ValueError("lifetime must be more than zero and at most ten minutes")
        self._issuer = issuer
        self._audience = audience.rstrip("/")
        self._algorithm = algorithm
        self._key_id = key_id or None
        self._lifetime = lifetime
        self._key = private_key.replace("\\n", "\n").strip()
        try:
            jwt.encode({"probe": True}, self._key, algorithm=algorithm)
        except (jwt.InvalidKeyError, ValueError, TypeError) as exc:
            raise ValueError(f"the private key cannot sign {algorithm}: {exc}") from exc

    @property
    def issuer(self) -> str:
        return self._issuer

    @property
    def audience(self) -> str:
        return self._audience

    def sign(
        self,
        client_id: str,
        sub: str,
        use: TokenUse = TokenUse.DATA,
        *,
        now: datetime | None = None,
    ) -> AppToken:
        """A token of kind ``use`` for the person your app knows as ``sub``, for ``client_id``.

        ``sub`` is your own, stable id for the person: never reuse it for someone else.
        """
        if not client_id:
            raise ValueError("client_id is required: the app the token is for (its azp)")
        if not sub:
            raise ValueError("sub is required: your own id for the person")
        issued = (now or datetime.now(UTC)).replace(microsecond=0)
        expires = issued + self._lifetime
        claims: dict[str, str | int] = {
            "iss": self._issuer,
            "aud": self._audience,
            "azp": client_id,
            "sub": sub,
            "iat": int(issued.timestamp()),
            "exp": int(expires.timestamp()),
            # Required on a connect hint (it connects once), harmless on the others.
            "jti": str(uuid.uuid4()),
        }
        if use is not TokenUse.DATA:
            claims["token_use"] = use.value
        headers = {"kid": self._key_id} if self._key_id else None
        token = jwt.encode(claims, self._key, algorithm=self._algorithm, headers=headers)
        return AppToken(token=token, expires_at=expires)

    def data_token(self, client_id: str, sub: str, *, now: datetime | None = None) -> AppToken:
        """The bearer for ``/partner/v1`` and ``/org/v1`` calls as the person."""
        return self.sign(client_id, sub, TokenUse.DATA, now=now)

    def connect_hint(self, client_id: str, sub: str, *, now: datetime | None = None) -> AppToken:
        """Connects a member's account at your app to their Geena account, once."""
        return self.sign(client_id, sub, TokenUse.CONNECT, now=now)

    def claim_link(self, client_id: str, sub: str, *, now: datetime | None = None) -> AppToken:
        """Opens Geena's claim page for a person your organization imported."""
        return self.sign(client_id, sub, TokenUse.CLAIM, now=now)
