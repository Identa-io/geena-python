"""Keeping a connection's tokens fresh. Storage and locking stay the integrator's.

A :class:`TokenSet` is what an app persists per connection (a user's) or per org session (a
member's): the access token and when it expires, the refresh token, the scope, and the
``request_id`` for a data connection. :func:`ensure_fresh` returns a usable access token,
refreshing when the current one is within ``skew`` of expiry.

Refresh tokens rotate and are single-use, so two workers refreshing the same row at once end
the token family. Call :func:`ensure_fresh` while holding a lock on the stored row (a
``SELECT ... FOR UPDATE``, a per-connection mutex) and persist the returned set before releasing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from geena.errors import GeenaError, ReconnectRequired
from geena.oauth import OAuthClient, TokenResponse

#: Refresh this long before the access token expires: clocks drift and requests take time.
DEFAULT_SKEW = timedelta(seconds=60)


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    expires_at: datetime
    refresh_token: str | None
    scope: str = ""
    request_id: str | None = None

    @classmethod
    def from_response(cls, tokens: TokenResponse, *, now: datetime | None = None) -> TokenSet:
        issued = now or datetime.now(UTC)
        return cls(
            access_token=tokens.access_token,
            expires_at=issued + timedelta(seconds=max(0, tokens.expires_in)),
            refresh_token=tokens.refresh_token,
            scope=tokens.scope,
            request_id=tokens.request_id,
        )

    def updated(self, tokens: TokenResponse, *, now: datetime | None = None) -> TokenSet:
        """The set after a refresh: new access token, the rotated refresh token when one came,
        the ``request_id`` kept (a refresh does not repeat it)."""
        fresh = TokenSet.from_response(tokens, now=now)
        return replace(
            fresh,
            refresh_token=tokens.refresh_token or self.refresh_token,
            request_id=fresh.request_id or self.request_id,
            scope=tokens.scope or self.scope,
        )

    def grants(self, scope: str) -> bool:
        return scope in self.scope.split()

    def is_fresh(self, *, now: datetime | None = None, skew: timedelta = DEFAULT_SKEW) -> bool:
        return self.expires_at - (now or datetime.now(UTC)) > skew


async def ensure_fresh(
    tokens: TokenSet,
    oauth: OAuthClient,
    *,
    skew: timedelta = DEFAULT_SKEW,
    now: datetime | None = None,
) -> TokenSet:
    """Return ``tokens`` if the access token is still usable, else the refreshed set.

    Raises :class:`ReconnectRequired` when there is no refresh token or Geena refuses the
    refresh — the connection can only be re-established through a new ceremony.
    """
    if tokens.is_fresh(now=now, skew=skew):
        return tokens
    if not tokens.refresh_token:
        raise ReconnectRequired("no refresh token stored for this connection")
    try:
        response = await oauth.refresh(tokens.refresh_token)
    except GeenaError as exc:
        raise ReconnectRequired(str(exc)) from exc
    return tokens.updated(response, now=now)
