from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from geena import (
    ORGANIZATION_SCOPE,
    GeenaClient,
    GeenaOAuthError,
    ReconnectRequired,
    TokenSet,
    ensure_fresh,
)
from geena.pkce import challenge_for, new_state, new_verifier
from tests.conftest import FakeGeena


def _jwt(payload: dict[str, object]) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"eyJhbGciOiJFZERTQSJ9.{body}.sig"


def test_pkce_pair_is_s256() -> None:
    verifier = new_verifier()
    assert 43 <= len(verifier) <= 128
    assert challenge_for("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == (
        "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )
    assert new_state() != new_state()


def test_authorize_url_for_a_data_connection(client: GeenaClient) -> None:
    url = client.oauth.authorize_url(
        redirect_uri="https://app.example.com/geena/callback",
        state="st",
        code_challenge="ch",
        manifest_id="m-1",
    )
    parsed = urlparse(url)
    assert parsed.scheme == "https" and parsed.netloc == "api.test.geena.eu"
    assert parsed.path == "/oauth/authorize"
    q = parse_qs(parsed.query)
    assert q["response_type"] == ["code"]
    assert q["client_id"] == ["acme-portal"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["manifest_id"] == ["m-1"]
    assert "scope" not in q


def test_authorize_url_for_organization_access_is_a_pure_login(client: GeenaClient) -> None:
    url = client.oauth.authorize_url(
        redirect_uri="https://office.example.com/cb",
        state="st",
        code_challenge="ch",
        scope=ORGANIZATION_SCOPE,
    )
    q = parse_qs(urlparse(url).query)
    assert q["scope"] == [ORGANIZATION_SCOPE]
    assert "manifest_id" not in q
    with pytest.raises(ValueError):
        client.oauth.authorize_url(
            redirect_uri="https://office.example.com/cb",
            state="st",
            code_challenge="ch",
            scope=ORGANIZATION_SCOPE,
            manifest_id="m-1",
        )


def test_public_base_url_only_changes_the_browser_facing_url() -> None:
    c = GeenaClient(
        "http://host.docker.internal:8080",
        client_id="a",
        client_secret="b",
        public_base_url="http://localhost:8080",
    )
    url = c.oauth.authorize_url(
        redirect_uri="http://localhost:3005/cb", state="s", code_challenge="c"
    )
    assert url.startswith("http://localhost:8080/oauth/authorize?")


async def test_exchange_code_sends_client_credentials_and_returns_request_id(
    client: GeenaClient, geena: FakeGeena
) -> None:
    geena.on(
        "POST",
        "/oauth/token",
        json_body={
            "access_token": _jwt({"sub": "u-1", "email": "anna@example.com", "scope": "profile"}),
            "token_type": "Bearer",
            "expires_in": 900,
            "refresh_token": "r-1",
            "scope": "offline_access profile",
            "request_id": "req-1",
        },
    )
    tokens = await client.oauth.exchange_code(
        code="c", code_verifier="v", redirect_uri="https://app.example.com/cb"
    )
    form = parse_qs(geena.last().content.decode())
    assert form["grant_type"] == ["authorization_code"]
    assert form["client_id"] == ["acme-portal"] and form["client_secret"] == ["s3cret"]
    assert form["code_verifier"] == ["v"]
    assert tokens.request_id == "req-1"
    assert not tokens.grants("organization")
    claims = client.oauth.decode_claims(tokens.access_token)
    assert (claims.sub, claims.email) == ("u-1", "anna@example.com")


async def test_refresh_refusal_is_an_oauth_error(client: GeenaClient, geena: FakeGeena) -> None:
    geena.on(
        "POST",
        "/oauth/token",
        status=400,
        json_body={"error": "interaction_required", "error_description": "consent revoked"},
    )
    with pytest.raises(GeenaOAuthError) as info:
        await client.oauth.refresh("r-old")
    assert info.value.code == "interaction_required"
    assert info.value.interaction_required


async def test_ensure_fresh_refreshes_only_inside_the_skew(
    client: GeenaClient, geena: FakeGeena
) -> None:
    now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    fresh = TokenSet("a-1", now + timedelta(minutes=10), "r-1", "profile", "req-1")
    assert await ensure_fresh(fresh, client.oauth, now=now) is fresh
    assert geena.calls == []

    geena.on(
        "POST",
        "/oauth/token",
        json_body={
            "access_token": "a-2",
            "expires_in": 900,
            "refresh_token": "r-2",
            "scope": "profile",
        },
    )
    stale = TokenSet("a-1", now + timedelta(seconds=30), "r-1", "profile", "req-1")
    rotated = await ensure_fresh(stale, client.oauth, now=now)
    assert (rotated.access_token, rotated.refresh_token) == ("a-2", "r-2")
    assert rotated.request_id == "req-1", "a refresh does not repeat the request id; keep it"
    assert rotated.expires_at == now + timedelta(seconds=900)


async def test_ensure_fresh_without_a_refresh_token_means_reconnect(client: GeenaClient) -> None:
    expired = TokenSet("a-1", datetime(2020, 1, 1, tzinfo=UTC), None, "profile")
    with pytest.raises(ReconnectRequired):
        await ensure_fresh(expired, client.oauth)


async def test_step_up_handoff_and_verify_url(client: GeenaClient, geena: FakeGeena) -> None:
    geena.on(
        "POST",
        "/oauth/step-up",
        json_body={
            "handoffId": "h-1",
            "token": "t-1",
            "requiredLevel": 2,
            "expiresAt": "2026-09-28T12:05:00Z",
        },
    )
    handoff = await client.oauth.step_up("a-1")
    assert geena.last().headers["Authorization"] == "Bearer a-1"
    assert handoff.verify_url("https://dashboard.test.geena.eu") == (
        "https://dashboard.test.geena.eu/verify/step-up?handoff=h-1&token=t-1"
    )
    assert client.grant_url("req-1") == "https://dashboard.test.geena.eu/personal/connections/req-1"
