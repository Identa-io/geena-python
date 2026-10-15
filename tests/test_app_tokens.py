from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

from geena import AppTokenSigner, GeenaClient, TokenUse

ISSUER = "https://flow.example.com"
AUDIENCE = "https://api.test.geena.eu"
NOW = datetime(2026, 10, 15, 9, 30, 12, 345678, tzinfo=UTC)


def _pem(key: ec.EllipticCurvePrivateKey | rsa.RSAPrivateKey | ed25519.Ed25519PrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


@pytest.fixture
def ec_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def _decode(token: str, key: Any, algorithm: str = "ES256") -> dict[str, Any]:
    claims: dict[str, Any] = jwt.decode(
        token,
        key.public_key(),
        algorithms=[algorithm],
        audience=AUDIENCE,
        issuer=ISSUER,
        options={"verify_exp": False, "verify_iat": False},
    )
    return claims


def test_a_data_token_carries_the_documented_claims(ec_key: ec.EllipticCurvePrivateKey) -> None:
    signer = AppTokenSigner(
        issuer=ISSUER, private_key=_pem(ec_key), audience=AUDIENCE + "/", key_id="flow-2026-10"
    )
    token = signer.data_token("dff-staff", "staff-42", now=NOW)

    claims = _decode(token.token, ec_key)
    assert {k: claims[k] for k in ("iss", "aud", "azp", "sub")} == {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "azp": "dff-staff",
        "sub": "staff-42",
    }
    assert claims["exp"] - claims["iat"] == 600
    assert claims["iat"] == int(NOW.replace(microsecond=0).timestamp())
    assert claims["jti"] and "token_use" not in claims
    assert jwt.get_unverified_header(token.token) == {
        "alg": "ES256",
        "kid": "flow-2026-10",
        "typ": "JWT",
    }
    assert token.expires_at == NOW.replace(microsecond=0) + timedelta(minutes=10)
    assert token.expires_within(timedelta(minutes=10), now=NOW)
    assert not token.expires_within(timedelta(minutes=5), now=NOW)


def test_connect_hints_and_claim_links_name_their_use(ec_key: ec.EllipticCurvePrivateKey) -> None:
    signer = AppTokenSigner(issuer=ISSUER, private_key=_pem(ec_key), audience=AUDIENCE)

    hint = _decode(signer.connect_hint("dff-staff", "staff-42").token, ec_key)
    link = _decode(signer.claim_link("dff-client", "investor-7").token, ec_key)
    again = _decode(signer.sign("dff-staff", "staff-42", TokenUse.CONNECT).token, ec_key)

    assert hint["token_use"] == "connect" and hint["azp"] == "dff-staff"
    assert link["token_use"] == "claim" and link["azp"] == "dff-client"
    assert hint["jti"] != again["jti"], "a connect hint connects once: every hint is new"
    assert "kid" not in jwt.get_unverified_header(signer.claim_link("dff-client", "i").token)


def test_a_pem_from_an_environment_variable_signs(ec_key: ec.EllipticCurvePrivateKey) -> None:
    one_line = _pem(ec_key).strip().replace("\n", "\\n")
    signer = AppTokenSigner(issuer=ISSUER, private_key=one_line, audience=AUDIENCE)
    assert _decode(signer.data_token("dff-client", "investor-7").token, ec_key)["sub"] == (
        "investor-7"
    )


def test_every_algorithm_geena_accepts_signs_with_a_key_of_its_kind() -> None:
    ed = ed25519.Ed25519PrivateKey.generate()
    eddsa = AppTokenSigner(
        issuer=ISSUER, private_key=_pem(ed), audience=AUDIENCE, algorithm="EdDSA"
    )
    assert _decode(eddsa.data_token("app", "u").token, ed, "EdDSA")["azp"] == "app"

    rs = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ps256 = AppTokenSigner(
        issuer=ISSUER, private_key=_pem(rs), audience=AUDIENCE, algorithm="PS256"
    )
    assert _decode(ps256.data_token("app", "u").token, rs, "PS256")["sub"] == "u"


def test_what_geena_would_refuse_is_refused_here(ec_key: ec.EllipticCurvePrivateKey) -> None:
    pem = _pem(ec_key)
    with pytest.raises(ValueError, match="ten minutes"):
        AppTokenSigner(
            issuer=ISSUER, private_key=pem, audience=AUDIENCE, lifetime=timedelta(minutes=11)
        )
    with pytest.raises(ValueError, match="cannot sign"):
        rs = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        AppTokenSigner(issuer=ISSUER, private_key=_pem(rs), audience=AUDIENCE, algorithm="ES256")
    with pytest.raises(ValueError, match="not one Geena accepts"):
        AppTokenSigner(issuer=ISSUER, private_key=pem, audience=AUDIENCE, algorithm="HS256")
    with pytest.raises(ValueError, match="issuer"):
        AppTokenSigner(issuer="", private_key=pem, audience=AUDIENCE)
    signer = AppTokenSigner(issuer=ISSUER, private_key=pem, audience=AUDIENCE)
    with pytest.raises(ValueError, match="sub"):
        signer.data_token("dff-client", "")
    with pytest.raises(ValueError, match="client_id"):
        signer.data_token("", "investor-7")


async def test_a_claim_link_opens_the_claim_page(client: GeenaClient) -> None:
    assert client.claim_url("eyJ.claim.link") == (
        "https://dashboard.test.geena.eu/claim/eyJ.claim.link"
    )
    async with GeenaClient("https://api.test.geena.eu", client_id="dff-client") as bare:
        with pytest.raises(ValueError, match="dashboard_base_url"):
            bare.claim_url("eyJ.claim.link")
