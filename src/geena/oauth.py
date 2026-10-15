"""The connect ceremony and the token endpoints: authorize URL, exchange, refresh, revoke.

These endpoints are not part of the OpenAPI documents; they follow the Partner API docs
(https://docs.test.geena.eu/partner-api/connect/). Two ceremonies share one flow:

- a **data connection**: ``manifest_id`` names the ask, the user consents once, the token
  exchange returns the connection's ``request_id`` — the address of every ``/partner/v1`` call;
- **organization access**: ``scope=ORGANIZATION_SCOPE`` and no manifest, a pure login for the
  organization's own back office. The scope means "if member": the token response's ``scope``
  says whether the person turned out to be one, and only then does the token open ``/org/v1``.

An app that signs its own tokens (:mod:`geena.app_tokens`) needs neither the exchange nor the
client secret: it sends a member through the same ceremony once, with a connect hint
(:meth:`OAuthClient.connect_url`), and calls both planes with its own tokens from then on.
"""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict

from geena.errors import GeenaError, GeenaOAuthError, GeenaTransportError
from geena.http import Transport, json_object, json_or_empty

#: The scope set of an organization-access ceremony: identity plus ``organization``.
ORGANIZATION_SCOPE = "profile offline_access organization"

#: The scope set of a staff connect: an app that signs its own tokens exchanges no code, so it
#: asks for no refresh token.
CONNECT_SCOPE = "profile organization"


class TokenResponse(BaseModel):
    """``POST /oauth/token`` on success (RFC 6749 §5.1 plus Geena's ``request_id``)."""

    model_config = ConfigDict(extra="ignore")

    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 0
    refresh_token: str | None = None
    scope: str = ""
    #: The connection this ceremony minted or resumed; absent on a pure-login ceremony.
    request_id: str | None = None

    def grants(self, scope: str) -> bool:
        return scope in self.scope.split()


class TokenClaims(BaseModel):
    """What a partner access token says about its user — read, not verified.

    The token was minted by Geena and received over TLS on the client-authenticated exchange,
    so the claims are trustworthy for the app's own bookkeeping (which user a connection
    belongs to). Never accept them from anywhere else.
    """

    model_config = ConfigDict(extra="ignore")

    sub: str = ""
    email: str = ""
    scope: str = ""
    client_id: str = ""


class OAuthClient:
    def __init__(
        self,
        transport: Transport,
        *,
        client_id: str,
        client_secret: str | None = None,
        public_base_url: str | None = None,
    ) -> None:
        self._transport = transport
        self._client_id = client_id
        self._client_secret = client_secret or None
        self._public_base = (public_base_url or transport.base_url).rstrip("/")

    @property
    def client_id(self) -> str:
        return self._client_id

    def authorize_url(
        self,
        *,
        redirect_uri: str,
        state: str,
        code_challenge: str,
        manifest_id: str | None = None,
        request_id: str | None = None,
        scope: str | None = None,
        app_token: str | None = None,
    ) -> str:
        """The URL to open in the popup (synchronously, in the click handler).

        ``redirect_uri`` must sit on one of the app's registered origins (scheme + host + port,
        matched exactly). Pass ``manifest_id`` for a data connection, ``request_id`` to resume an
        invitation your organization sent, or ``scope=ORGANIZATION_SCOPE`` with neither for the
        back-office sign-in. ``app_token`` is a connect hint (see :meth:`connect_url`).
        """
        organization = bool(scope) and "organization" in (scope or "").split()
        if organization and (manifest_id or request_id):
            raise ValueError("organization access is a pure login: no manifest_id or request_id")
        if app_token and not organization:
            raise ValueError("a connect hint rides only on an organization-access sign-in")
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if manifest_id:
            params["manifest_id"] = manifest_id
        if request_id:
            params["request_id"] = request_id
        if scope:
            params["scope"] = scope
        if app_token:
            params["app_token"] = app_token
        return f"{self._public_base}/oauth/authorize?{urlencode(params)}"

    def connect_url(
        self, *, redirect_uri: str, state: str, code_challenge: str, connect_hint: str
    ) -> str:
        """Connect a member's account at your app to their Geena account, once.

        ``connect_hint`` is :meth:`AppTokenSigner.connect_hint` for the member, signed for this
        client. They sign in to Geena, accept the organization-access screen, and from then on
        your app's tokens for their ``sub`` reach Geena as them. The redirect carries a code as
        usual; there is nothing to exchange. Geena refuses the connect before showing anything
        when they are not a member of your organization, when either account is already
        connected to another, or when the hint is expired, of another kind, or already used.
        """
        return self.authorize_url(
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=code_challenge,
            scope=CONNECT_SCOPE,
            app_token=connect_hint,
        )

    async def exchange_code(
        self, *, code: str, code_verifier: str, redirect_uri: str
    ) -> TokenResponse:
        """Redeem the single-use code (valid 5 minutes) with the PKCE verifier and the same
        redirect URI as at authorize."""
        return await self._token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
            }
        )

    async def refresh(self, refresh_token: str) -> TokenResponse:
        """Rotate: the response carries a NEW refresh token — persist it before anything else.

        A superseded or revoked refresh token is theft evidence to Geena: the whole token family
        goes, and the user must reconnect. Hold a lock over the stored row while refreshing.
        """
        return await self._token({"grant_type": "refresh_token", "refresh_token": refresh_token})

    async def revoke(self, token: str) -> None:
        """RFC 7009: present any refresh token and the whole grant is torn down."""
        response = await self._transport.form(
            "/oauth/revoke",
            {"client_id": self._client_id, "client_secret": self._secret(), "token": token},
        )
        if response.status_code >= 500:
            raise GeenaTransportError(f"geena revoke failed ({response.status_code})")

    @staticmethod
    def decode_claims(access_token: str) -> TokenClaims:
        """Read the JWT payload without verifying the signature (see :class:`TokenClaims`)."""
        try:
            _, payload, _ = access_token.split(".")
            padded = payload + "=" * (-len(payload) % 4)
            data: Any = json.loads(base64.urlsafe_b64decode(padded))
        except (ValueError, TypeError) as exc:
            raise GeenaTransportError("access token is not a JWT") from exc
        if not isinstance(data, dict):
            raise GeenaTransportError("access token payload is not an object")
        return TokenClaims.model_validate(data)

    def _secret(self) -> str:
        if self._client_secret is None:
            raise GeenaError(
                "this client has no client secret: an app that signs its own tokens "
                "exchanges no code and refreshes nothing"
            )
        return self._client_secret

    async def _token(self, form: dict[str, str]) -> TokenResponse:
        response = await self._transport.form(
            "/oauth/token",
            {"client_id": self._client_id, "client_secret": self._secret(), **form},
        )
        if response.status_code == 200:
            return TokenResponse.model_validate(json_object(response))
        body = json_or_empty(response)
        if body.get("error"):
            raise GeenaOAuthError(str(body["error"]), str(body.get("error_description") or ""))
        raise GeenaTransportError(f"geena token endpoint failed ({response.status_code})")
