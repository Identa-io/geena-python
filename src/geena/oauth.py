"""The connect ceremony and the token endpoints: authorize URL, exchange, refresh, revoke, step-up.

These endpoints are not part of the OpenAPI documents; they follow the Partner API docs
(https://docs.test.geena.eu/partner-api/connect/). Two ceremonies share one flow:

- a **data connection**: ``manifest_id`` names the ask, the user consents once, the token
  exchange returns the connection's ``request_id`` — the address of every ``/partner/v1`` call;
- **organization access**: ``scope=ORGANIZATION_SCOPE`` and no manifest, a pure login for the
  organization's own back office. The scope means "if member": the token response's ``scope``
  says whether the person turned out to be one, and only then does the token open ``/org/v1``.
"""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field

from geena.errors import GeenaAPIError, GeenaOAuthError, GeenaTransportError
from geena.http import Transport, json_object, json_or_empty

#: The scope set of an organization-access ceremony: identity plus ``organization``.
ORGANIZATION_SCOPE = "profile offline_access organization"


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


class StepUpHandoff(BaseModel):
    """``POST /oauth/step-up``: the one-time hand-off to Geena's hosted verification page."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    handoff_id: str = Field(alias="handoffId")
    token: str
    required_level: int = Field(alias="requiredLevel")
    expires_at: str = Field(alias="expiresAt")

    def verify_url(self, dashboard_base_url: str) -> str:
        """The hosted page to open for the user (a popup, like the connect ceremony)."""
        query = urlencode({"handoff": self.handoff_id, "token": self.token})
        return f"{dashboard_base_url.rstrip('/')}/verify/step-up?{query}"


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
        client_secret: str,
        public_base_url: str | None = None,
    ) -> None:
        self._transport = transport
        self._client_id = client_id
        self._client_secret = client_secret
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
    ) -> str:
        """The URL to open in the popup (synchronously, in the click handler).

        ``redirect_uri`` must sit on one of the app's registered origins (scheme + host + port,
        matched exactly). Pass ``manifest_id`` for a data connection, ``request_id`` to resume an
        invitation your organization sent, or ``scope=ORGANIZATION_SCOPE`` with neither for the
        back-office sign-in.
        """
        if scope and "organization" in scope.split() and (manifest_id or request_id):
            raise ValueError("organization access is a pure login: no manifest_id or request_id")
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
        return f"{self._public_base}/oauth/authorize?{urlencode(params)}"

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
            {"client_id": self._client_id, "client_secret": self._client_secret, "token": token},
        )
        if response.status_code >= 500:
            raise GeenaTransportError(f"geena revoke failed ({response.status_code})")

    async def step_up(self, access_token: str) -> StepUpHandoff:
        """Mint the hand-off that lets the user unseal their vault on Geena's hosted page.

        A Standard account needs no step-up: Geena answers ``400`` and this raises
        :class:`GeenaOAuthError` — the original refusal was something else.
        """
        try:
            body = await self._transport.json("POST", "/oauth/step-up", token=access_token)
        except GeenaAPIError as exc:
            raise GeenaOAuthError(exc.code, exc.message) from exc
        return StepUpHandoff.model_validate(body)

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

    async def _token(self, form: dict[str, str]) -> TokenResponse:
        response = await self._transport.form(
            "/oauth/token",
            {"client_id": self._client_id, "client_secret": self._client_secret, **form},
        )
        if response.status_code == 200:
            return TokenResponse.model_validate(json_object(response))
        body = json_or_empty(response)
        if body.get("error"):
            raise GeenaOAuthError(str(body["error"]), str(body.get("error_description") or ""))
        raise GeenaTransportError(f"geena token endpoint failed ({response.status_code})")
